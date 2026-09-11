"""HTTP surface: identity, SSE stream, approvals."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import update

from app.config import API_PREFIX
from app.core.enums import PendingActionStatus
from app.db.models import PendingAction
from app.engine.events import EventType
from app.main import create_app
from tests.integration.conftest import all_events, make_gate, open_session
from tests.support import Paused, PausingApprovalPort, SideEffects, generate_rsa_keys, make_token, read_sse, stub_registry

pytestmark = pytest.mark.integration


class RecordingRunner:
    def __init__(self) -> None:
        self.resumed: list[tuple] = []

    async def resume(self, ctx, decision):
        self.resumed.append((ctx, decision))
        return None

    async def aclose(self) -> None:
        pass


def _client(container) -> httpx.AsyncClient:
    app = create_app(container.settings)
    app.state.container = container
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine.test")


async def _pending_action(container, tenant_id, user_id):
    ctx = await open_session(container, tenant_id, user_id)
    port = PausingApprovalPort()
    with pytest.raises(Paused):
        await make_gate(container, container.registry, port).call_tool(
            ctx, "orchestrator", "send_note", {"to": "ceo@acme.test", "text": "hello"}, call_id="c1"
        )
    return ctx, port.requests[0].pending_action_id


# --------------------------------------------------------------------------- identity


async def test_health_is_public(make_container):
    container = await make_container()
    async with _client(container) as client:
        assert (await client.get(f"{API_PREFIX}/health")).json() == {"status": "UP"}
        ready = await client.get(f"{API_PREFIX}/health/ready")
        assert ready.status_code == 200 and ready.json()["checks"] == {"database": "UP", "redis": "UP"}


async def test_approvals_require_a_valid_token_and_workspace_membership(
    make_container, rsa_keys, tenant_id, user_id, workspace_service
):
    container = await make_container()
    token = make_token(rsa_keys, user_id)
    url = f"{API_PREFIX}/approvals"
    async with _client(container) as client:
        assert (await client.get(url, headers={"X-Tenant-Id": str(tenant_id)})).status_code == 401
        forged = make_token(generate_rsa_keys(), user_id)
        assert (await client.get(url, headers={"X-Tenant-Id": str(tenant_id), "Cookie": f"access_token={forged}"})).status_code == 401

        cookie = {"Cookie": f"access_token={token}"}
        assert (await client.get(url, headers=cookie)).status_code == 400
        assert (await client.get(url, headers={**cookie, "X-Tenant-Id": "workspace-1"})).status_code == 400
        denied = await client.get(url, headers={**cookie, "X-Tenant-Id": str(uuid4())})
        assert denied.status_code == 403 and denied.json()["code"] == "TENANT_ACCESS_DENIED"

        ok = await client.get(url, headers={**cookie, "X-Tenant-Id": str(tenant_id)})
        assert ok.status_code == 200
        bearer = await client.get(url, headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": str(tenant_id)})
        assert bearer.status_code == 200

        # Membership is cached, but a removed member is refused once the cache is refreshed.
        workspace_service.remove(user_id, tenant_id)
        await container.redis.flushdb()
        assert (await client.get(url, headers={**cookie, "X-Tenant-Id": str(tenant_id)})).status_code == 403


# --------------------------------------------------------------------------- approvals


async def test_list_and_approve_resumes_the_session(make_container, rsa_keys, tenant_id, user_id):
    container = await make_container(registry=stub_registry(SideEffects()))
    runner = RecordingRunner()
    container.runner = runner
    ctx, action_id = await _pending_action(container, tenant_id, user_id)
    headers = {"Cookie": f"access_token={make_token(rsa_keys, user_id)}", "X-Tenant-Id": str(tenant_id)}

    async with _client(container) as client:
        listed = (await client.get(f"{API_PREFIX}/approvals", headers=headers)).json()
        assert [item["id"] for item in listed] == [str(action_id)]
        assert listed[0]["preview"] == {"to": "ceo@acme.test", "body": "hello"}

        response = await client.post(
            f"{API_PREFIX}/approvals/{action_id}/decision", headers=headers, json={"decision": "approve"}
        )
        assert response.status_code == 200 and response.json()["status"] == "APPROVED"
        assert response.json()["resolved_by"] == str(user_id)

        again = await client.post(f"{API_PREFIX}/approvals/{action_id}/decision", headers=headers, json={"decision": "reject"})
        assert again.status_code == 409

    [(resume_ctx, decision)] = runner.resumed
    assert (resume_ctx.session_id, resume_ctx.tenant_id, resume_ctx.user_id) == (ctx.session_id, tenant_id, user_id)
    assert decision == {"pending_action_id": str(action_id), "status": "APPROVED"}
    resolved = [e for e in await all_events(container, ctx.session_id) if e["type"] == EventType.APPROVAL_RESOLVED]
    assert resolved and resolved[0]["data"]["status"] == "APPROVED"


async def test_edit_validates_arguments_against_the_tool(make_container, rsa_keys, tenant_id, user_id):
    container = await make_container(registry=stub_registry(SideEffects()))
    container.runner = RecordingRunner()
    _, action_id = await _pending_action(container, tenant_id, user_id)
    headers = {"Cookie": f"access_token={make_token(rsa_keys, user_id)}", "X-Tenant-Id": str(tenant_id)}
    url = f"{API_PREFIX}/approvals/{action_id}/decision"

    async with _client(container) as client:
        assert (await client.post(url, headers=headers, json={"decision": "edit"})).status_code == 422
        bad = await client.post(url, headers=headers, json={"decision": "edit", "args": {"to": "x", "text": "hi"}})
        assert bad.status_code == 422
        smuggle = await client.post(
            url, headers=headers, json={"decision": "edit", "args": {"to": "cfo@acme.test", "text": "hi", "tenant_id": "x"}}
        )
        assert smuggle.status_code == 422
        good = await client.post(
            url, headers=headers, json={"decision": "edit", "args": {"to": "cfo@acme.test", "text": "Revised"}, "note": "tone"}
        )
        assert good.status_code == 200
        body = good.json()
        assert body["status"] == "EDITED" and body["edited_args"] == {"to": "cfo@acme.test", "text": "Revised"}
        assert body["args"] == {"to": "ceo@acme.test", "text": "hello"}  # original kept for audit


async def test_other_users_and_expired_approvals_cannot_be_decided(
    make_container, rsa_keys, tenant_id, user_id, workspace_service
):
    container = await make_container(registry=stub_registry(SideEffects()))
    container.runner = RecordingRunner()
    _, action_id = await _pending_action(container, tenant_id, user_id)
    colleague = uuid4()
    workspace_service.add(colleague, tenant_id)
    url = f"{API_PREFIX}/approvals/{action_id}/decision"

    async with _client(container) as client:
        other = {"Cookie": f"access_token={make_token(rsa_keys, colleague)}", "X-Tenant-Id": str(tenant_id)}
        assert (await client.post(url, headers=other, json={"decision": "approve"})).status_code == 404
        assert (await client.get(f"{API_PREFIX}/approvals", headers=other)).json() == []

        async with container.engine.begin() as conn:
            await conn.execute(update(PendingAction).values(expires_at=PendingAction.created_at))
        owner = {"Cookie": f"access_token={make_token(rsa_keys, user_id)}", "X-Tenant-Id": str(tenant_id)}
        expired = await client.post(url, headers=owner, json={"decision": "approve"})
        assert expired.status_code == 409
    assert (await container.pending_actions.get(tenant_id=tenant_id, action_id=action_id)).status == PendingActionStatus.PENDING


# --------------------------------------------------------------------------- SSE


async def test_phase0_done_when_stub_call_through_gate_is_audited_and_streamed(
    make_container, serve, rsa_keys, tenant_id, user_id
):
    """Phase 0 acceptance: a stub tool call flows through the gate, gets audited, and its
    events stream to a test client."""
    container = await make_container(registry=stub_registry(SideEffects()))
    base_url = await serve(container)
    ctx = await open_session(container, tenant_id, user_id)
    url = f"{API_PREFIX}/sessions/{ctx.session_id}/events"

    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        reader = asyncio.create_task(read_sse(client, url, token=make_token(rsa_keys, user_id), count=2))
        await asyncio.sleep(0.3)
        gate = make_gate(container, container.registry, PausingApprovalPort())
        result = await gate.call_tool(ctx, "orchestrator", "lookup_facts", {"topic": "Acme"}, call_id="c1")
        streamed = await reader

    assert result.ok
    assert [event["data"]["type"] for event in streamed] == ["tool_call", "tool_result"]
    assert streamed[1]["data"]["data"]["outcome"] == "EXECUTED"
    [audit] = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert (audit.tool, audit.outcome) == ("lookup_facts", "EXECUTED")


async def test_sse_streams_envelopes_live_and_resumes_after_last_event_id(make_container, serve, rsa_keys, tenant_id, user_id):
    container = await make_container()
    base_url = await serve(container)
    ctx = await open_session(container, tenant_id, user_id)
    token = make_token(rsa_keys, user_id)
    url = f"{API_PREFIX}/sessions/{ctx.session_id}/events"
    await container.events.emit(ctx.session_id, EventType.STEP_STARTED, {"step": "plan"})

    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        reader = asyncio.create_task(read_sse(client, url, token=token, count=2))
        await asyncio.sleep(0.3)  # connected and blocked waiting: the next event arrives live
        await container.events.emit(ctx.session_id, EventType.PROGRESS, {"pct": 50})
        first, second = await reader

        assert first["data"]["type"] == "step_started" and first["data"]["data"] == {"step": "plan"}
        assert first["data"]["session_id"] == str(ctx.session_id) and first["data"]["ts"]
        assert second["data"]["type"] == "progress"

        [replayed] = await read_sse(client, url, token=token, count=1, last_event_id=first["id"])
        assert replayed["id"] == second["id"]


async def test_sse_is_only_visible_to_the_session_owner(make_container, serve, rsa_keys, tenant_id, user_id, workspace_service):
    container = await make_container()
    base_url = await serve(container)
    ctx = await open_session(container, tenant_id, user_id)
    url = f"{API_PREFIX}/sessions/{ctx.session_id}/events"
    colleague = uuid4()
    workspace_service.add(colleague, tenant_id)

    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        assert (await client.get(url)).status_code == 401
        other = await client.get(url, headers={"Cookie": f"access_token={make_token(rsa_keys, colleague)}"})
        assert other.status_code == 404
        bad_cursor = await client.get(
            url, headers={"Cookie": f"access_token={make_token(rsa_keys, user_id)}", "Last-Event-ID": "abc"}
        )
        assert bad_cursor.status_code == 400
