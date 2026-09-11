"""Phase 3 guardrails through the real orchestrator graph, gate, ledger and runner.

"Done when": every write is gated + approved + audited, and a forced tool failure
compensates cleanly — after the rep approves the undo (nothing is reversed without it).
The model, Composio and data-pipeline are doubles; everything else is real.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text

from app.config import API_PREFIX
from app.core.clock import utcnow
from app.core.enums import PendingActionStatus, SagaStatus, SessionStatus
from app.db.models import PendingAction
from app.engine.orchestrator import turn_input
from app.engine.runner import context_for
from app.models.types import Completion, Message, Role, StreamDone, TextDelta, ToolCall, Usage
from app.platform.composio_client import ConnectorError
from app.tools.adapters.google_calendar import calendar_tools
from app.tools.adapters.slack import slack_tools
from app.tools.registry import ToolRegistry
from tests.integration.conftest import all_events, settle_runs, start_run
from tests.support import FakeConnector, SideEffects, make_token, stub_registry

pytestmark = pytest.mark.integration

START = (utcnow() + timedelta(days=3)).replace(hour=15, minute=0, second=0, microsecond=0).isoformat()
EVENT = {"title": "Acme demo", "start": START, "time_zone": "Europe/London", "attendees": ["jane@acme.test"]}
SLACK = {"channel": "sales", "text": "Acme demo is booked"}

Decide = Callable[[list[Message]], tuple[str, list[tuple[str, dict[str, Any]]]]]


class Brain:
    """A model double that decides from the conversation, so a resumed step decides the same."""

    def __init__(self, decide: Decide, *, tokens: int = 100) -> None:
        self.decide = decide
        self.tokens = tokens
        self.name = "gemini"
        self.tasks: list[Any] = []

    async def stream(self, task: Any, models: Any):
        self.tasks.append(task)
        content, calls = self.decide(list(task.messages))
        if content:
            yield TextDelta(content)
        message = Message(
            role=Role.ASSISTANT,
            content=content,
            tool_calls=tuple(ToolCall(id=f"call_{len(self.tasks)}_{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)),
        )
        yield StreamDone(Completion(message=message, provider="gemini", model="scripted", usage=Usage(self.tokens, 10)))


def _results_since_user(messages: list[Message]) -> list[dict[str, Any]]:
    last_user = max(i for i, m in enumerate(messages) if m.role is Role.USER)
    return [json.loads(m.content) | {"tool": m.name} for m in messages[last_user:] if m.role is Role.TOOL]


def _report(messages: list[Message]) -> str:
    return " | ".join(f"{r['tool']}: {r.get('summary') or r.get('error') or r['outcome']}" for r in _results_since_user(messages))


def book_and_announce(messages: list[Message]) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
    last = messages[-1]
    if last.role is Role.USER:
        if "undo" in last.content:
            booked = [
                json.loads(m.content)
                for m in messages
                if m.role is Role.TOOL and m.name == "create_calendar_event" and '"action_id"' in m.content
            ]
            return "Undoing it.", [("undo_actions", {"action_ids": [booked[-1]["action_id"]], "reason": "the rep asked"})]
        if "slack only" in last.content:
            return "Posting.", [("send_slack_message", SLACK)]
        if "book only" in last.content:
            return "Booking.", [("create_calendar_event", EVENT)]
        return "Booking and announcing.", [("create_calendar_event", EVENT), ("send_slack_message", SLACK)]
    return "Report: " + _report(messages), []


def _connector(*, slack_fails: bool = True) -> FakeConnector:
    return FakeConnector(
        responses={"GOOGLECALENDAR_CREATE_EVENT": {"response_data": {"id": "evt-1", "htmlLink": "https://calendar.google.com/e/1"}}},
        failures={"SLACK_SEND_MESSAGE": ConnectorError("SLACK_SEND_MESSAGE failed: channel_not_found")} if slack_fails else {},
    )


async def _container(make_container, connector: FakeConnector, decide: Decide = book_and_announce, **kwargs):
    registry = ToolRegistry([*calendar_tools(connector), *slack_tools(connector)])
    return await make_container(providers={"gemini": Brain(decide)}, registry=registry, **kwargs)


async def _wait_for_status(container, session_id: UUID, status: SessionStatus, timeout: float = 10.0):
    deadline = asyncio.get_running_loop().time() + timeout
    row = None
    while asyncio.get_running_loop().time() < deadline:
        row = await container.sessions.get(session_id)
        if row.status == status:
            return row
        await asyncio.sleep(0.05)
    raise AssertionError(f"session {session_id} never reached {status} (is {row.status if row else None})")


async def _decide(container, session_id: UUID, tool: str, status: PendingActionStatus = PendingActionStatus.APPROVED) -> PendingAction:
    """Wait for the session's next approval, check it is for ``tool``, decide it, and run on."""
    session = await _wait_for_status(container, session_id, SessionStatus.AWAITING_APPROVAL)
    [action] = await container.pending_actions.list_for_user(
        tenant_id=session.tenant_id, user_id=session.user_id, status=PendingActionStatus.PENDING, session_id=session_id
    )
    assert action.tool == tool, f"expected an approval for {tool}, got {action.tool}"
    await container.pending_actions.resolve(
        tenant_id=session.tenant_id, action_id=action.id, status=status, resolved_by=session.user_id
    )
    task = await container.runner.resume(context_for(session), {"pending_action_id": str(action.id)})
    if task is not None:
        await task
    return action


async def _start(container, tenant_id, user_id, prompt: str):
    return await start_run(container, tenant_id, user_id, turn_input(prompt), user_message=prompt)


async def _continue(container, session_id: UUID, prompt: str) -> None:
    session = await _wait_for_status(container, session_id, SessionStatus.DONE)
    assert await container.runner.continue_session(session, turn_input(prompt), user_message=prompt) is not None


async def test_phase3_done_when_a_forced_failure_compensates_after_the_rep_approves(make_container, tenant_id, user_id):
    connector = _connector()
    container = await _container(make_container, connector)
    ctx = await _start(container, tenant_id, user_id, "Book the Acme demo and tell #sales")

    booked = await _decide(container, ctx.session_id, "create_calendar_event")
    assert booked.preview["kind"] == "calendar_event" and booked.preview["time_zone"] == "Europe/London"
    await _decide(container, ctx.session_id, "send_slack_message")  # approved, then Slack fails
    undo = await _decide(container, ctx.session_id, "undo_actions")
    await settle_runs(container)

    # The undo card listed exactly what would be reversed, and why.
    assert undo.preview["kind"] == "undo" and "channel_not_found" in undo.preview["reason"]
    [offered] = undo.preview["actions"]
    assert offered["label"] == "Delete the calendar event 'Acme demo' and email attendees a cancellation"
    assert offered["summary"].startswith("Calendar event 'Acme demo' created")
    assert undo.preview["cannot_undo"] == []

    session = await container.sessions.get(ctx.session_id)
    assert session.status == SessionStatus.DONE
    assert connector.slugs() == ["GOOGLECALENDAR_CREATE_EVENT", "SLACK_SEND_MESSAGE", "GOOGLECALENDAR_DELETE_EVENT"]
    assert connector.executions[-1]["arguments"]["event_id"] == "evt-1"

    # Every write was gated, approved and audited; the undo step has its own audit row.
    approvals = await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id, status=None)
    assert sorted((a.tool, a.status) for a in approvals) == [
        ("create_calendar_event", "APPROVED"), ("send_slack_message", "APPROVED"), ("undo_actions", "APPROVED"),
    ]
    audits = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert [(a.tool, a.outcome) for a in audits] == [
        ("create_calendar_event", "EXECUTED"),
        ("send_slack_message", "FAILED"),
        ("undo:create_calendar_event", "EXECUTED"),
        ("undo_actions", "EXECUTED"),
    ]
    assert audits[2].pending_action_id == undo.id and audits[2].args["event_id"] == "evt-1"
    steps = await container.ledger.list_steps(tenant_id=tenant_id, session_id=ctx.session_id)
    assert [(s.action, s.status, s.turn) for s in steps] == [
        ("create_calendar_event", SagaStatus.COMPENSATED, 1),
        ("send_slack_message", SagaStatus.FAILED, 1),
        ("undo_actions", SagaStatus.DONE, 1),
    ]

    # The model saw the undo's outcome and reported it.
    answer = (await container.runner.snapshot(ctx)).values["final_answer"]
    assert "undo_actions: Undid 1 of 1 action" in answer
    events = await all_events(container, ctx.session_id)
    assert [e["data"]["tool"] for e in events if e["type"] == "awaiting_approval"] == [
        "create_calendar_event", "send_slack_message", "undo_actions",
    ]
    assert events[-1]["type"] == "done"

    # The transcript shows the proposed undo like any other step.
    from app.api.sessions import transcript_from

    items = transcript_from((await container.runner.snapshot(ctx)).values["messages"])
    assert [(i.kind, i.tool, i.outcome) for i in items if i.tool == "undo_actions"] == [
        ("tool_call", "undo_actions", None), ("tool_result", "undo_actions", "EXECUTED"),
    ]


async def test_nothing_is_undone_when_the_rep_rejects_the_undo(make_container, tenant_id, user_id):
    connector = _connector()
    container = await _container(make_container, connector)
    ctx = await _start(container, tenant_id, user_id, "Book the Acme demo and tell #sales")

    await _decide(container, ctx.session_id, "create_calendar_event")
    await _decide(container, ctx.session_id, "send_slack_message")
    await _decide(container, ctx.session_id, "undo_actions", PendingActionStatus.REJECTED)
    await settle_runs(container)

    assert "GOOGLECALENDAR_DELETE_EVENT" not in connector.slugs()
    steps = await container.ledger.list_steps(tenant_id=tenant_id, session_id=ctx.session_id)
    assert [(s.action, s.status) for s in steps] == [
        ("create_calendar_event", SagaStatus.DONE), ("send_slack_message", SagaStatus.FAILED),
    ]
    assert (await container.sessions.get(ctx.session_id)).status == SessionStatus.DONE
    assert "undo_actions: rejected by reviewer" in (await container.runner.snapshot(ctx)).values["final_answer"]


async def test_an_expired_approval_ends_the_wait_and_offers_to_undo_what_was_done(make_container, tenant_id, user_id):
    connector = _connector(slack_fails=False)
    container = await _container(make_container, connector)
    ctx = await _start(container, tenant_id, user_id, "Book the Acme demo and tell #sales")

    await _decide(container, ctx.session_id, "create_calendar_event")
    await _wait_for_status(container, ctx.session_id, SessionStatus.AWAITING_APPROVAL)
    [waiting] = await container.pending_actions.list_for_user(
        tenant_id=tenant_id, user_id=user_id, status=PendingActionStatus.PENDING
    )
    assert waiting.tool == "send_slack_message"
    async with container.engine.begin() as conn:
        await conn.execute(text("UPDATE agent.pending_action SET expires_at = now() - interval '1 second' WHERE id = :id"), {"id": waiting.id})

    assert await container.runner.expire_stale_approvals() == [waiting.id]
    await _decide(container, ctx.session_id, "undo_actions")
    await settle_runs(container)

    assert connector.slugs() == ["GOOGLECALENDAR_CREATE_EVENT", "GOOGLECALENDAR_DELETE_EVENT"]  # Slack never ran
    expired = await container.pending_actions.get(tenant_id=tenant_id, action_id=waiting.id)
    assert expired.status == PendingActionStatus.EXPIRED
    steps = await container.ledger.list_steps(tenant_id=tenant_id, session_id=ctx.session_id)
    assert [(s.action, s.status) for s in steps] == [
        ("create_calendar_event", SagaStatus.COMPENSATED), ("undo_actions", SagaStatus.DONE),
    ]
    events = await all_events(container, ctx.session_id)
    assert {"pending_action_id": str(waiting.id), "status": "EXPIRED", "resolved_by": None} in [
        e["data"] for e in events if e["type"] == "approval_resolved"
    ]
    audits = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert ("send_slack_message", "EXPIRED") in [(a.tool, a.outcome) for a in audits]


async def test_the_automatic_offer_covers_only_the_current_request_and_the_rep_can_undo_earlier_ones(
    make_container, tenant_id, user_id
):
    connector = _connector()
    container = await _container(make_container, connector)
    ctx = await _start(container, tenant_id, user_id, "book only the demo")
    await _decide(container, ctx.session_id, "create_calendar_event")
    await settle_runs(container)

    # Request 2 fails, but it completed nothing: no undo is offered for request 1's event.
    await _continue(container, ctx.session_id, "slack only: announce it")
    await _decide(container, ctx.session_id, "send_slack_message")
    await settle_runs(container)
    assert (await container.sessions.get(ctx.session_id)).status == SessionStatus.DONE
    assert [a.tool for a in await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id, status=None)].count("undo_actions") == 0

    # Request 3: the rep asks; the model undoes request 1's event by its action_id.
    await _continue(container, ctx.session_id, "please undo the calendar event")
    await _decide(container, ctx.session_id, "undo_actions")
    await settle_runs(container)

    assert connector.slugs()[-1] == "GOOGLECALENDAR_DELETE_EVENT"
    steps = await container.ledger.list_steps(tenant_id=tenant_id, session_id=ctx.session_id)
    assert [(s.action, s.status, s.turn) for s in steps] == [
        ("create_calendar_event", SagaStatus.COMPENSATED, 1),
        ("send_slack_message", SagaStatus.FAILED, 2),
        ("undo_actions", SagaStatus.DONE, 3),
    ]
    assert (await container.sessions.get(ctx.session_id)).turn == 3


async def test_undo_refuses_actions_that_are_not_this_sessions_or_are_already_undone(make_container, tenant_id, user_id):
    connector = _connector()
    container = await _container(make_container, connector)
    first = await _start(container, tenant_id, user_id, "book only the demo")
    await _decide(container, first.session_id, "create_calendar_event")
    await settle_runs(container)
    [step] = await container.ledger.list_steps(tenant_id=tenant_id, session_id=first.session_id)

    other = context_for(await container.sessions.create(tenant_id=tenant_id, user_id=user_id, mode=first.mode))
    foreign = await container.gate.call_tool(other, "orchestrator", "undo_actions", {"action_ids": [str(step.id)]}, call_id="u1")
    assert foreign.outcome.value == "INVALID" and "not an action of this session" in (foreign.error or "")
    assert await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id, session_id=other.session_id, status=None) == []

    research = await container.gate.call_tool(first, "research", "undo_actions", {"action_ids": [str(step.id)]}, call_id="u2")
    assert research.outcome.value == "DENIED"  # only the coordinator may undo


async def test_a_looping_model_is_halted_cleanly(make_container, tenant_id, user_id):
    def loop(messages: list[Message]):
        return "Checking again.", [("lookup_facts", {"topic": "Acme"})]

    container = await make_container(providers={"gemini": Brain(loop)}, registry=stub_registry(SideEffects()))
    ctx = await _start(container, tenant_id, user_id, "What do we know about Acme?")
    await settle_runs(container)

    session = await container.sessions.get(ctx.session_id)
    assert session.status == SessionStatus.HALTED and session.ended_at is not None
    events = await all_events(container, ctx.session_id)
    assert events[-1]["type"] == "halted" and events[-1]["data"]["reason"] == "LOOP"
    assert "repeating the same step ('lookup_facts'" in events[-1]["data"]["final_answer"]
    audits = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert [a.tool for a in audits] == ["lookup_facts", "lookup_facts"]  # the third call never ran
    values = (await container.runner.snapshot(ctx)).values
    assert values["messages"][-2]["role"] == "tool" and "safety limit" in values["messages"][-2]["content"]

    # A halted session takes a new request.
    assert await container.runner.continue_session(session, turn_input("try something else"), user_message="x") is not None
    await settle_runs(container)


async def test_the_step_and_token_limits_halt_a_turn(make_container, tenant_id, user_id):
    def wander(messages: list[Message]):
        return "Still looking.", [("lookup_facts", {"topic": f"topic {len(messages)}"})]

    container = await make_container(
        providers={"gemini": Brain(wander)}, registry=stub_registry(SideEffects()), settings_overrides={"max_steps_per_turn": 2}
    )
    ctx = await _start(container, tenant_id, user_id, "Research everything")
    await settle_runs(container)
    events = await all_events(container, ctx.session_id)
    assert events[-1]["type"] == "halted" and events[-1]["data"]["reason"] == "STEP_LIMIT"
    assert (await container.sessions.get(ctx.session_id)).status == SessionStatus.HALTED

    costly = await make_container(
        providers={"gemini": Brain(wander, tokens=600)}, registry=stub_registry(SideEffects()),
        settings_overrides={"max_tokens_per_turn": 1000},
    )
    ctx = await _start(costly, tenant_id, user_id, "Research everything")
    await settle_runs(costly)
    events = await all_events(costly, ctx.session_id)
    assert events[-1]["data"]["reason"] == "TOKEN_LIMIT"
    assert await costly.budgets.tokens_used_today(tenant_id) >= 1200  # usage is also counted for the daily budget


async def test_budgets_are_enforced_before_a_turn_starts(make_container, rsa_keys, tenant_id, user_id):
    from app.main import create_app

    container = await make_container(
        providers={"gemini": Brain(lambda messages: ("Hi.", []))},
        settings_overrides={"turns_per_minute_per_user": 1, "tokens_per_day_per_tenant": 1000},
    )
    app = create_app(container.settings)
    app.state.container = container
    headers = {"Cookie": f"access_token={make_token(rsa_keys, user_id)}", "X-Tenant-Id": str(tenant_id)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine.test") as client:
        first = await client.post(f"{API_PREFIX}/chat", headers=headers, json={"message": "hi", "time_zone": "Asia/Kolkata"})
        assert first.status_code == 202
        second = await client.post(f"{API_PREFIX}/chat", headers=headers, json={"message": "again"})
        assert second.status_code == 429 and "per minute" in second.json()["message"]

        await settle_runs(container)
        await container.redis.flushdb()
        await container.budgets.record_tokens(tenant_id, 5000)
        over = await client.post(f"{API_PREFIX}/chat", headers=headers, json={"message": "more"})
        assert over.status_code == 429 and "budget for today" in over.json()["message"]

    values = (await container.runner.snapshot(context_for(await container.sessions.get(UUID(first.json()["session_id"]))))).values
    assert values["time_zone"] == "Asia/Kolkata"
    assert "(Asia/Kolkata)" in container.router._providers["gemini"].tasks[0].system


async def test_after_the_undo_decision_the_model_can_only_report_back(make_container, tenant_id, user_id):
    def stubborn(messages: list[Message]):
        if messages[-1].role is Role.USER:
            return "Booking and announcing.", [("create_calendar_event", EVENT), ("send_slack_message", SLACK)]
        return "", [("send_slack_message", SLACK)]  # keeps retrying the failed post, even after the undo

    connector = _connector()
    brain = Brain(stubborn)
    container = await make_container(
        providers={"gemini": brain}, registry=ToolRegistry([*calendar_tools(connector), *slack_tools(connector)])
    )
    ctx = await _start(container, tenant_id, user_id, "Book the Acme demo and tell #sales")
    await _decide(container, ctx.session_id, "create_calendar_event")
    await _decide(container, ctx.session_id, "send_slack_message")
    await _decide(container, ctx.session_id, "undo_actions")
    await settle_runs(container)

    assert (await container.sessions.get(ctx.session_id)).status == SessionStatus.DONE
    assert connector.slugs().count("SLACK_SEND_MESSAGE") == 1  # the retry never reached the gate
    last_task = brain.tasks[-1]
    assert last_task.allow_tool_calls is False and "Take no further action in this request" in last_task.system
    answer = (await container.runner.snapshot(ctx)).values["final_answer"]
    assert answer.startswith("An action didn't go through, so I stopped this request. Undo: Undid 1 of 1 action")
