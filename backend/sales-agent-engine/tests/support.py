"""Test doubles: signed tokens, a fake workspace-service, stub tools, approval ports."""

from __future__ import annotations

import asyncio
import json
import operator
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict
from uuid import UUID

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import Field

from app.autonomy.policy import PolicyDecision, Verdict
from app.core.context import AgentContext
from app.core.enums import PendingActionStatus
from app.db.repositories import PendingActionRepository
from app.platform.langgraph_runtime import END, GraphSpec, current_context
from app.tools.gate import ApprovalRequest, ToolGate
from app.tools.registry import ToolDefinition, ToolRegistry
from app.tools.types import (
    ToolAccessDenied,
    ToolCategory,
    ToolInput,
    ToolInvocation,
    ToolKind,
    ToolOutput,
    ToolScope,
)

# --------------------------------------------------------------------------- tokens


@dataclass(frozen=True)
class RsaKeys:
    private_pem: str
    public_pem: str


def generate_rsa_keys() -> RsaKeys:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return RsaKeys(private_pem=private_pem, public_pem=public_pem)


def make_token(
    keys: RsaKeys,
    user_id: UUID,
    *,
    issuer: str = "rolesync-test-issuer",
    token_type: str = "ACCESS",
    expires_in: int = 3600,
    **overrides: Any,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": issuer,
        "sub": "display-name",
        "userId": str(user_id),
        "email": "rep@example.com",
        "tokenType": token_type,
        "scope": "read write",
        "iat": now,
        "exp": now + expires_in,
    }
    claims.update(overrides)
    claims = {key: value for key, value in claims.items() if value is not None}
    return jwt.encode(claims, keys.private_pem, algorithm="RS256")


# --------------------------------------------------------------------------- workspace-service


@dataclass
class FakeWorkspaceService:
    """Answers ``GET /api/v1/workspaces`` like workspace-service does."""

    memberships: dict[UUID, set[UUID]] = field(default_factory=dict)
    calls: int = 0

    def add(self, user_id: UUID, tenant_id: UUID) -> None:
        self.memberships.setdefault(user_id, set()).add(tenant_id)

    def remove(self, user_id: UUID, tenant_id: UUID) -> None:
        self.memberships.get(user_id, set()).discard(tenant_id)

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls += 1
            if request.url.path != "/api/v1/workspaces":
                return httpx.Response(404)
            user_id = UUID(request.headers["X-User-Id"])
            if user_id not in self.memberships:
                return httpx.Response(404, json={"message": "Workspace profile not found"})
            body = [{"workspaceId": str(ws), "name": "WS", "isActive": True} for ws in self.memberships[user_id]]
            return httpx.Response(200, json=body)

        return httpx.MockTransport(handler)


# --------------------------------------------------------------------------- stub tools


@dataclass
class SideEffects:
    """Records what stub write tools 'did' in the outside world."""

    sent: list[dict[str, Any]] = field(default_factory=list)


class LookupArgs(ToolInput):
    topic: str = Field(min_length=1)


class NoteArgs(ToolInput):
    to: str = Field(min_length=3)
    text: str = Field(min_length=1, max_length=500)


def stub_registry(
    effects: SideEffects, *, acl_denies: bool = False, acl_breaks: bool = False, read_delay: float = 0.0
) -> ToolRegistry:
    async def lookup(inv: ToolInvocation) -> ToolOutput:
        if read_delay:
            await asyncio.sleep(read_delay)
        args = inv.args
        assert isinstance(args, LookupArgs)
        return ToolOutput(data={"topic": args.topic, "facts": ["a", "b"]}, summary=f"2 facts about {args.topic}")

    async def send_note(inv: ToolInvocation) -> ToolOutput:
        args = inv.args
        assert isinstance(args, NoteArgs)
        ref = f"msg-{len(effects.sent) + 1}"
        effects.sent.append({"to": args.to, "text": args.text, "tenant": str(inv.ctx.tenant_id), "ref": ref})
        return ToolOutput(data={"message_id": ref}, summary=f"note sent to {args.to}", ref_id=ref)

    async def broken_send(inv: ToolInvocation) -> ToolOutput:
        raise RuntimeError("smtp relay unavailable")

    async def acl(ctx: AgentContext, args: ToolInput) -> None:
        if acl_denies:
            raise ToolAccessDenied("recipient belongs to another workspace")
        if acl_breaks:
            raise ConnectionError("directory service down")

    return ToolRegistry(
        [
            ToolDefinition(
                name="lookup_facts",
                description="Look up facts",
                kind=ToolKind.READ,
                scope=ToolScope.READ,
                category=ToolCategory.KNOWLEDGE,
                input_model=LookupArgs,
                handler=lookup,
            ),
            ToolDefinition(
                name="send_note",
                description="Send a note",
                kind=ToolKind.WRITE,
                scope=ToolScope.COMMUNICATION,
                category=ToolCategory.COMMUNICATION,
                input_model=NoteArgs,
                handler=send_note,
                acl=acl,
                preview=lambda args: {"to": args.to, "body": args.text},
                undo=lambda args: {"action": "recall_note", "to": args.to},
            ),
            ToolDefinition(
                name="broken_send",
                description="Always fails",
                kind=ToolKind.WRITE,
                scope=ToolScope.COMMUNICATION,
                category=ToolCategory.COMMUNICATION,
                input_model=NoteArgs,
                handler=broken_send,
            ),
        ]
    )


# --------------------------------------------------------------------------- approval ports + policies


class Paused(Exception):
    """Stands in for a graph interrupt when the gate is exercised outside a graph."""


class PausingApprovalPort:
    def __init__(self) -> None:
        self.requests: list[ApprovalRequest] = []

    async def wait_for_decision(self, request: ApprovalRequest) -> None:
        self.requests.append(request)
        raise Paused(str(request.pending_action_id))


class DecidedApprovalPort:
    """Behaves like a resumed interrupt: the decision is already recorded."""

    async def wait_for_decision(self, request: ApprovalRequest) -> None:
        return None


class ResolvingApprovalPort:
    """A reviewer who answers instantly."""

    def __init__(
        self,
        pending: PendingActionRepository,
        status: PendingActionStatus,
        reviewer: UUID,
        edited_args: dict[str, Any] | None = None,
        note: str | None = None,
    ) -> None:
        self._pending = pending
        self._status = status
        self._reviewer = reviewer
        self._edited = edited_args
        self._note = note

    async def wait_for_decision(self, request: ApprovalRequest) -> None:
        await self._pending.resolve(
            tenant_id=request.tenant_id,
            action_id=request.pending_action_id,
            status=self._status,
            resolved_by=self._reviewer,
            edited_args=self._edited,
            note=self._note,
        )


class AllowAllPolicy:
    async def evaluate(self, ctx: AgentContext, tool: ToolDefinition, args: ToolInput) -> PolicyDecision:
        return PolicyDecision(Verdict.ALLOW, "test envelope allows everything")


class BrokenPolicy:
    async def evaluate(self, ctx: AgentContext, tool: ToolDefinition, args: ToolInput) -> PolicyDecision:
        raise RuntimeError("goal store unavailable")


# --------------------------------------------------------------------------- graph


class NoteState(TypedDict):
    outcomes: Annotated[list[str], operator.add]


def note_graph(gate: ToolGate) -> GraphSpec:
    """One node that sends a note through the gate: the smallest graph with a write."""

    async def act(state: dict[str, Any]) -> dict[str, Any]:
        ctx = current_context()
        result = await gate.call_tool(
            ctx, "orchestrator", "send_note", {"to": "ceo@acme.test", "text": "Following up"}, call_id="call-1"
        )
        return {"outcomes": [result.outcome.value]}

    return GraphSpec(state_schema=NoteState, nodes={"act": act}, entry="act", edges=[("act", END)])


# --------------------------------------------------------------------------- SSE client


async def read_sse(
    client: httpx.AsyncClient,
    url: str,
    *,
    token: str | None,
    count: int,
    last_event_id: str | None = None,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """Read ``count`` events (``{"id", "data"}``) from an SSE endpoint, then disconnect."""
    headers = {"Accept": "text/event-stream"}
    if token:
        headers["Cookie"] = f"access_token={token}"
    if last_event_id:
        headers["Last-Event-ID"] = last_event_id

    events: list[dict[str, Any]] = []

    async def consume() -> None:
        async with client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            current: dict[str, Any] = {}
            async for line in response.aiter_lines():
                if line == "":
                    if "data" in current:
                        events.append(current)
                        if len(events) >= count:
                            return
                    current = {}
                elif line.startswith(":"):
                    continue  # keep-alive ping
                else:
                    name, _, value = line.partition(":")
                    value = value.removeprefix(" ")
                    current[name] = json.loads(value) if name == "data" else value

    await asyncio.wait_for(consume(), timeout)
    return events
