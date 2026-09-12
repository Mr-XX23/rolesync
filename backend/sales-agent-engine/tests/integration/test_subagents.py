"""Phase 5: the orchestrator delegating real work to sub-agents, through the real graph, gate and runner.

"Done when": the orchestrator delegates a task across sub-agents, and no sub-agent can exceed its
scope. The model is a double; the graph, gate, approvals, audit, checkpoints and runner are real.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import pytest
from pydantic import Field

from app.core.enums import PendingActionStatus, SessionStatus
from app.engine.delegation import DELEGATE_TOOL
from app.engine.orchestrator import turn_input
from app.engine.runner import context_for
from app.models.types import Completion, Message, Role, StreamDone, TextDelta, ToolCall, Usage
from app.tools.registry import ToolDefinition, ToolRegistry
from app.tools.types import ToolCategory, ToolInput, ToolInvocation, ToolKind, ToolOutput, ToolScope
from tests.integration.conftest import settle_runs, start_run

pytestmark = pytest.mark.integration


class LookUpArgs(ToolInput):
    about: str = Field(min_length=1)


class NoteArgs(ToolInput):
    to: str = Field(min_length=1)
    text: str = Field(min_length=1)


def _registry() -> ToolRegistry:
    """One read (anyone), one send (outreach's scope) and one pricing write (quote's scope)."""

    async def look_up(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, LookUpArgs)
        return ToolOutput(data={"about": args.about, "found": f"{args.about} renewed last year"}, summary=f"found notes on {args.about}")

    async def send_note(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, NoteArgs)
        return ToolOutput(data={"to": args.to}, summary=f"note sent to {args.to}", ref_id="note-1")

    return ToolRegistry([
        ToolDefinition(name="look_up", description="Look something up", kind=ToolKind.READ, scope=ToolScope.READ,
                       category=ToolCategory.KNOWLEDGE, input_model=LookUpArgs, handler=look_up),
        ToolDefinition(name="send_note", description="Send a note to someone", kind=ToolKind.WRITE,
                       scope=ToolScope.COMMUNICATION, category=ToolCategory.COMMUNICATION, input_model=NoteArgs,
                       handler=send_note),
    ])


def _tool_results(messages: list[Message], name: str) -> list[dict[str, Any]]:
    return [json.loads(message.content) for message in messages if message.role is Role.TOOL and message.name == name]


class Brain:
    """Plays the orchestrator and every sub-agent, deciding from the conversation it is given,
    so a resumed step decides the same as before the pause."""

    name = "gemini"

    def __init__(self) -> None:
        self.tasks: list[Any] = []

    def _decide(self, task: Any) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
        messages = list(task.messages)
        last = messages[-1]
        if task.purpose == "subagent:research":
            about = messages[0].content.split("about ")[-1].strip(" .")
            if last.role is Role.USER:
                return "", [("look_up", {"about": about})]
            found = _tool_results(messages, "look_up")
            return f"Brief on {about}: {found[0]['data']['found'] if found else 'nothing found'}", []
        if task.purpose == "subagent:outreach":
            if last.role is Role.USER:
                return "", [("send_note", {"to": "jane@acme.test", "text": messages[0].content[:200]})]
            sent = _tool_results(messages, "send_note")
            return f"Note: {sent[0].get('summary') or sent[0].get('error')}", []

        # the orchestrator
        delegated = _tool_results(messages, DELEGATE_TOOL)
        briefs = [item for item in delegated if item.get("data", {}).get("agent") == "research"]
        if last.role is Role.USER:
            return "Looking into both.", [
                (DELEGATE_TOOL, {"agent": "research", "task": "Write a short brief about Acme"}),
                (DELEGATE_TOOL, {"agent": "research", "task": "Write a short brief about Globex"}),
            ]
        if len(briefs) >= 2 and len(delegated) == 2:
            context = "\n".join(str(item["data"]["answer"]) for item in briefs)
            return "Writing to them.", [(DELEGATE_TOOL, {"agent": "outreach", "task": "Email Jane what we learned", "context": context})]
        return "Here is what happened: " + " | ".join(str(item.get("summary")) for item in delegated), []

    async def stream(self, task: Any, models: Any):
        self.tasks.append(task)
        content, calls = self._decide(task)
        if content:
            yield TextDelta(content)
        message = Message(
            role=Role.ASSISTANT,
            content=content,
            tool_calls=tuple(ToolCall(id=f"c{len(self.tasks)}_{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)),
        )
        yield StreamDone(Completion(message=message, provider="gemini", model="scripted", usage=Usage(100, 20)))


async def _wait(container, session_id: UUID, status: SessionStatus, timeout: float = 20.0):
    deadline = asyncio.get_running_loop().time() + timeout
    row = None
    while asyncio.get_running_loop().time() < deadline:
        row = await container.sessions.get(session_id)
        if row.status == status:
            return row
        await asyncio.sleep(0.05)
    audits = await container.ledger.list_audit(tenant_id=row.tenant_id, session_id=session_id)
    detail = [(a.agent, a.tool, a.outcome, (a.result_summary or '')[:80]) for a in audits]
    raise AssertionError(f"session never reached {status} (is {row.status if row else None}) audits={detail}")


async def test_phase5_done_when_the_orchestrator_delegates_across_sub_agents(make_container, tenant_id, user_id):
    brain = Brain()
    container = await make_container(providers={"gemini": brain}, registry=_registry())

    ctx = await start_run(container, tenant_id, user_id, turn_input("Prep Acme and Globex, then write to Jane"),
                          user_message="Prep Acme and Globex, then write to Jane")
    await settle_runs(container)

    # The outreach sub-agent's send pauses the whole run, and the approval names it.
    session = await _wait(container, ctx.session_id, SessionStatus.AWAITING_APPROVAL)
    [action] = await container.pending_actions.list_for_user(
        tenant_id=tenant_id, user_id=user_id, status=PendingActionStatus.PENDING, session_id=ctx.session_id
    )
    assert (action.tool, action.agent) == ("send_note", "outreach")

    await container.pending_actions.resolve(tenant_id=tenant_id, action_id=action.id, status=PendingActionStatus.APPROVED, resolved_by=user_id)
    task = await container.runner.resume(context_for(session), {"pending_action_id": str(action.id)})
    if task is not None:
        await task
    await settle_runs(container)
    await _wait(container, ctx.session_id, SessionStatus.DONE)

    # Two research sub-agents thought in the same step, then outreach ran on their briefs.
    purposes = [task.purpose for task in brain.tasks]
    assert purposes.count("subagent:research") == 4 and purposes.count("subagent:outreach") >= 2
    assert purposes.index("subagent:outreach") > max(index for index, p in enumerate(purposes) if p == "subagent:research")

    history = (await container.runner.snapshot(context_for(await container.sessions.get(ctx.session_id)))).values["messages"]
    messages = [Message.from_dict(item) for item in history]
    # Result-only: the planner sees the delegate results, never the sub-agents' own steps.
    assert {message.name for message in messages if message.role is Role.TOOL} == {DELEGATE_TOOL}
    delegated = _tool_results(messages, DELEGATE_TOOL)
    assert [item["data"]["agent"] for item in delegated] == ["research", "research", "outreach"]
    assert "Brief on Acme" in delegated[0]["data"]["answer"] and "Brief on Globex" in delegated[1]["data"]["answer"]
    assert [step["tool"] for step in delegated[2]["data"]["steps"]] == ["send_note"]
    assert "note sent to jane@acme.test" in delegated[2]["summary"]

    # Every call is audited under the agent that made it.
    audits = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    by_agent = {(audit.agent, audit.tool) for audit in audits}
    assert by_agent == {("orchestrator", DELEGATE_TOOL), ("research", "look_up"), ("outreach", "send_note")}
    assert [audit.outcome for audit in audits if audit.tool == "send_note"] == ["EXECUTED"]


async def test_a_sub_agent_cannot_reach_past_its_own_scope(make_container, tenant_id, user_id):
    class Overreaching(Brain):
        def _decide(self, task: Any) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
            messages = list(task.messages)
            if task.purpose == "subagent:research":
                if messages[-1].role is Role.USER:
                    # Neither is in the research agent's scope: starting another sub-agent, and sending.
                    return "", [(DELEGATE_TOOL, {"agent": "outreach", "task": "Send this for me instead"}),
                                ("send_note", {"to": "jane@acme.test", "text": "hi"})]
                refused = [json.loads(m.content) for m in messages if m.role is Role.TOOL]
                return "Could not do it: " + "; ".join(str(item.get("error")) for item in refused), []
            if messages[-1].role is Role.USER:
                return "", [(DELEGATE_TOOL, {"agent": "research", "task": "Find out about Acme and tell Jane"})]
            return "Done: " + " | ".join(str(item.get("summary")) for item in _tool_results(messages, DELEGATE_TOOL)), []

    brain = Overreaching()
    container = await make_container(providers={"gemini": brain}, registry=_registry())

    ctx = await start_run(container, tenant_id, user_id, turn_input("Find out about Acme and tell Jane"),
                          user_message="Find out about Acme and tell Jane")
    await settle_runs(container)
    await _wait(container, ctx.session_id, SessionStatus.DONE)

    # Nothing was sent, nothing was queued for approval, and the run carried on.
    assert await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id, status=None) == []
    audits = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    refused = {(audit.tool, audit.outcome) for audit in audits if audit.agent == "research"}
    assert refused == {("send_note", "DENIED"), (DELEGATE_TOOL, "DENIED")}
    denials = [audit for audit in audits if audit.outcome == "DENIED"]
    assert all("may not use" in (audit.result_summary or "") for audit in denials), [audit.result_summary for audit in denials]

    history = (await container.runner.snapshot(context_for(await container.sessions.get(ctx.session_id)))).values["messages"]
    [result] = _tool_results([Message.from_dict(item) for item in history], DELEGATE_TOOL)
    assert "may not use 'send_note'" in result["data"]["answer"]
