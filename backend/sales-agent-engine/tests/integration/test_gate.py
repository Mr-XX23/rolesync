"""The Tool Gate: tenant + scope + ACL + audit + approval pathway (Phase 0 "done when")."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.autonomy.policy import EscalateAllPolicy
from app.core.context import RunMode
from app.core.enums import PendingActionStatus, SagaStatus, ToolOutcome
from app.db.models import AuditEntry
from app.db.repositories.ledger import AuditFields, LedgerRepository
from tests.integration.conftest import all_events, make_gate, open_session
from tests.support import (
    AllowAllPolicy,
    BrokenPolicy,
    DecidedApprovalPort,
    Paused,
    PausingApprovalPort,
    ResolvingApprovalPort,
    SideEffects,
    stub_registry,
)

pytestmark = pytest.mark.integration

NOTE = {"to": "ceo@acme.test", "text": "Following up on our call"}


async def test_read_tool_executes_is_audited_and_streams_events(make_container, tenant_id, user_id):
    container = await make_container()
    gate = make_gate(container, stub_registry(SideEffects()), PausingApprovalPort())
    ctx = await open_session(container, tenant_id, user_id)

    result = await gate.call_tool(ctx, "research", "lookup_facts", {"topic": "Acme"}, call_id="c1")

    assert result.ok and result.outcome is ToolOutcome.EXECUTED
    assert result.data == {"topic": "Acme", "facts": ["a", "b"]}
    [audit] = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert (audit.agent, audit.tool, audit.outcome, audit.user_id) == ("research", "lookup_facts", "EXECUTED", user_id)
    assert audit.args == {"topic": "Acme"}
    events = await all_events(container, ctx.session_id)
    assert [e["type"] for e in events] == ["tool_call", "tool_result"]
    assert all(e["session_id"] == str(ctx.session_id) and e["ts"] for e in events)
    assert events[1]["data"]["summary"] == "2 facts about Acme"


async def test_research_agent_cannot_call_a_write_tool(make_container, tenant_id, user_id):
    container = await make_container()
    effects = SideEffects()
    gate = make_gate(container, stub_registry(effects), PausingApprovalPort())
    ctx = await open_session(container, tenant_id, user_id)

    result = await gate.call_tool(ctx, "research", "send_note", NOTE, call_id="c1")

    assert not result.ok and result.outcome is ToolOutcome.DENIED
    assert "COMMUNICATION" in (result.error or "")
    assert effects.sent == []
    assert await container.pending_actions.get_by_key(tenant_id=tenant_id, idempotency_key=f"{ctx.session_id}:c1") is None
    [audit] = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert audit.outcome == "DENIED"


@pytest.mark.parametrize(
    ("agent", "tool", "args", "outcome"),
    [
        ("orchestrator", "delete_everything", {}, ToolOutcome.DENIED),
        ("rogue-agent", "lookup_facts", {"topic": "x"}, ToolOutcome.DENIED),
        ("orchestrator", "lookup_facts", {"topic": "x", "tenant_id": str(uuid4())}, ToolOutcome.DENIED),
        ("orchestrator", "lookup_facts", {"topic": ""}, ToolOutcome.INVALID),
        ("orchestrator", "lookup_facts", {"topic": "x", "extra": 1}, ToolOutcome.INVALID),
    ],
    ids=["unknown-tool", "unknown-agent", "identity-smuggling", "bad-value", "unknown-field"],
)
async def test_calls_refused_before_execution_are_audited(make_container, tenant_id, user_id, agent, tool, args, outcome):
    container = await make_container()
    gate = make_gate(container, stub_registry(SideEffects()), PausingApprovalPort())
    ctx = await open_session(container, tenant_id, user_id)

    result = await gate.call_tool(ctx, agent, tool, args, call_id="c1")

    assert not result.ok and result.outcome is outcome
    [audit] = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert audit.outcome == outcome.value
    events = await all_events(container, ctx.session_id)
    assert [e["type"] for e in events] == ["tool_result"]


async def test_resource_acl_denial(make_container, tenant_id, user_id):
    container = await make_container()
    effects = SideEffects()
    gate = make_gate(container, stub_registry(effects, acl_denies=True), PausingApprovalPort())
    ctx = await open_session(container, tenant_id, user_id)

    result = await gate.call_tool(ctx, "orchestrator", "send_note", NOTE, call_id="c1")

    assert result.outcome is ToolOutcome.DENIED and "another workspace" in (result.error or "")
    assert effects.sent == []


async def test_broken_access_check_fails_the_call_not_the_run(make_container, tenant_id, user_id):
    container = await make_container()
    effects = SideEffects()
    gate = make_gate(container, stub_registry(effects, acl_breaks=True), PausingApprovalPort())
    ctx = await open_session(container, tenant_id, user_id)

    result = await gate.call_tool(ctx, "orchestrator", "send_note", NOTE, call_id="c1")

    assert result.outcome is ToolOutcome.FAILED and "could not verify access" in (result.error or "")
    assert effects.sent == []


async def test_autonomous_write_escalates_when_the_policy_itself_fails(make_container, tenant_id, user_id):
    container = await make_container()
    effects = SideEffects()
    ctx = await open_session(container, tenant_id, user_id, RunMode.AUTONOMOUS)
    gate = make_gate(container, stub_registry(effects), PausingApprovalPort(), policy=BrokenPolicy())

    with pytest.raises(Paused):
        await gate.call_tool(ctx, "orchestrator", "send_note", NOTE, call_id="c1")

    assert effects.sent == []
    events = await all_events(container, ctx.session_id)
    assert events[-1]["data"]["reason"] == "autonomy policy could not be evaluated"


async def test_interactive_write_pauses_for_approval_then_executes_exactly_once(make_container, tenant_id, user_id):
    container = await make_container()
    effects = SideEffects()
    registry = stub_registry(effects)
    ctx = await open_session(container, tenant_id, user_id)

    # 1) First pass: the gate records the pending action and pauses.
    pausing = PausingApprovalPort()
    with pytest.raises(Paused):
        await make_gate(container, registry, pausing).call_tool(ctx, "orchestrator", "send_note", NOTE, call_id="c1")
    [request] = pausing.requests
    pending = await container.pending_actions.get(tenant_id=tenant_id, action_id=request.pending_action_id)
    assert pending.status == "PENDING" and pending.args == NOTE and pending.agent == "orchestrator"
    assert pending.preview == {"to": "ceo@acme.test", "body": "Following up on our call"}
    assert effects.sent == []
    events = await all_events(container, ctx.session_id)
    assert [e["type"] for e in events] == ["tool_call", "awaiting_approval"]
    assert events[1]["data"]["pending_action_id"] == str(pending.id)

    # 2) Replay before a decision (node re-run): same approval, no duplicate row or events.
    with pytest.raises(Paused):
        await make_gate(container, registry, PausingApprovalPort()).call_tool(
            ctx, "orchestrator", "send_note", NOTE, call_id="c1"
        )
    assert len(await all_events(container, ctx.session_id)) == 2

    # 3) Human approves; the resumed call executes.
    await container.pending_actions.resolve(
        tenant_id=tenant_id, action_id=pending.id, status=PendingActionStatus.APPROVED, resolved_by=user_id
    )
    gate = make_gate(container, registry, DecidedApprovalPort())
    result = await gate.call_tool(ctx, "orchestrator", "send_note", NOTE, call_id="c1")

    assert result.ok and result.outcome is ToolOutcome.EXECUTED and result.pending_action_id == pending.id
    assert len(effects.sent) == 1 and effects.sent[0]["tenant"] == str(tenant_id)
    [step] = await container.ledger.list_steps(tenant_id=tenant_id, session_id=ctx.session_id)
    assert (step.status, step.ref_id, step.step_no) == (SagaStatus.DONE, "msg-1", 1)
    assert step.undo_action == {"tool": "send_note", "args": {"ref": "msg-1"}, "label": "Recall the note to ceo@acme.test"}
    assert result.action_id == step.id and result.undoable
    assert step.turn == ctx.turn
    audits = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert [a.outcome for a in audits] == ["EXECUTED"]
    assert audits[0].result == {"message_id": "msg-1"} and audits[0].pending_action_id == pending.id

    # 4) Replaying the executed call returns the recorded result without sending again.
    again = await gate.call_tool(ctx, "orchestrator", "send_note", NOTE, call_id="c1")
    assert again.duplicate and again.data == {"message_id": "msg-1"}
    assert len(effects.sent) == 1


async def test_rejected_write_never_runs(make_container, tenant_id, user_id):
    container = await make_container()
    effects = SideEffects()
    ctx = await open_session(container, tenant_id, user_id)
    port = ResolvingApprovalPort(container.pending_actions, PendingActionStatus.REJECTED, user_id, note="wrong tone")
    gate = make_gate(container, stub_registry(effects), port)

    result = await gate.call_tool(ctx, "orchestrator", "send_note", NOTE, call_id="c1")

    assert result.outcome is ToolOutcome.REJECTED and "wrong tone" in (result.error or "")
    assert effects.sent == []
    assert await container.ledger.list_steps(tenant_id=tenant_id, session_id=ctx.session_id) == []
    [audit] = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert audit.outcome == "REJECTED" and audit.pending_action_id == result.pending_action_id


async def test_edited_write_runs_with_the_reviewers_arguments(make_container, tenant_id, user_id):
    container = await make_container()
    effects = SideEffects()
    ctx = await open_session(container, tenant_id, user_id)
    edited = {"to": "cfo@acme.test", "text": "Revised wording"}
    port = ResolvingApprovalPort(container.pending_actions, PendingActionStatus.EDITED, user_id, edited_args=edited)
    gate = make_gate(container, stub_registry(effects), port)

    result = await gate.call_tool(ctx, "orchestrator", "send_note", NOTE, call_id="c1")

    assert result.ok
    assert effects.sent[0]["to"] == "cfo@acme.test" and effects.sent[0]["text"] == "Revised wording"
    [audit] = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert audit.args == edited


async def test_autonomous_write_escalates_when_outside_the_envelope(make_container, tenant_id, user_id):
    container = await make_container()
    effects = SideEffects()
    ctx = await open_session(container, tenant_id, user_id, RunMode.AUTONOMOUS)
    pausing = PausingApprovalPort()
    gate = make_gate(container, stub_registry(effects), pausing, policy=EscalateAllPolicy())

    with pytest.raises(Paused):
        await gate.call_tool(ctx, "orchestrator", "send_note", NOTE, call_id="c1")

    assert effects.sent == []
    events = await all_events(container, ctx.session_id)
    assert events[-1]["type"] == "awaiting_approval"
    assert "autonomy envelope" in events[-1]["data"]["reason"]


async def test_autonomous_write_inside_the_envelope_runs_without_a_human(make_container, tenant_id, user_id):
    container = await make_container()
    effects = SideEffects()
    ctx = await open_session(container, tenant_id, user_id, RunMode.AUTONOMOUS)
    pausing = PausingApprovalPort()
    gate = make_gate(container, stub_registry(effects), pausing, policy=AllowAllPolicy())

    result = await gate.call_tool(ctx, "orchestrator", "send_note", NOTE, call_id="c1")

    assert result.ok and pausing.requests == [] and len(effects.sent) == 1
    assert result.pending_action_id is None
    [audit] = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert audit.outcome == "EXECUTED" and audit.pending_action_id is None


async def test_failing_write_is_audited_and_marks_its_saga_step_failed(make_container, tenant_id, user_id):
    container = await make_container()
    ctx = await open_session(container, tenant_id, user_id, RunMode.AUTONOMOUS)
    gate = make_gate(container, stub_registry(SideEffects()), PausingApprovalPort(), policy=AllowAllPolicy())

    result = await gate.call_tool(ctx, "orchestrator", "broken_send", NOTE, call_id="c1")

    assert not result.ok and result.outcome is ToolOutcome.FAILED and "smtp relay unavailable" in (result.error or "")
    [step] = await container.ledger.list_steps(tenant_id=tenant_id, session_id=ctx.session_id)
    assert step.status == SagaStatus.FAILED and "smtp" in (step.error or "")
    [audit] = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert audit.outcome == "FAILED"


async def test_write_interrupted_mid_execution_is_not_blindly_retried(make_container, tenant_id, user_id):
    container = await make_container()
    effects = SideEffects()
    ctx = await open_session(container, tenant_id, user_id, RunMode.AUTONOMOUS)
    # A previous attempt recorded its saga step, then the process died before finishing.
    await container.ledger.begin_step(
        tenant_id=tenant_id,
        session_id=ctx.session_id,
        action="send_note",
        undo_action=None,
        idempotency_key=f"{ctx.session_id}:c1",
    )
    gate = make_gate(container, stub_registry(effects), PausingApprovalPort(), policy=AllowAllPolicy())

    result = await gate.call_tool(ctx, "orchestrator", "send_note", NOTE, call_id="c1")

    assert result.outcome is ToolOutcome.UNKNOWN and "MAY HAVE HAPPENED" in (result.error or "")
    assert effects.sent == []


@pytest.mark.parametrize(
    ("tool", "registry_options"),
    [("send_note", {"write_delay": 1.0}), ("unconfirmed_send", {})],
    ids=["timed-out", "connection-lost"],
)
async def test_a_write_that_gives_no_answer_is_unknown_and_never_sent_twice(
    make_container, tenant_id, user_id, tool, registry_options
):
    container = await make_container()
    effects = SideEffects()
    ctx = await open_session(container, tenant_id, user_id, RunMode.AUTONOMOUS)
    registry = stub_registry(effects, **registry_options)
    gate = make_gate(container, registry, PausingApprovalPort(), policy=AllowAllPolicy(), timeout_seconds=0.1)

    result = await gate.call_tool(ctx, "orchestrator", tool, NOTE, call_id="c1")

    assert result.outcome is ToolOutcome.UNKNOWN and "MAY HAVE HAPPENED" in (result.error or "")
    assert len(effects.sent) == 1  # it did go out
    [step] = await container.ledger.list_steps(tenant_id=tenant_id, session_id=ctx.session_id)
    assert step.status == SagaStatus.PENDING
    [audit] = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert audit.outcome == "UNKNOWN"

    # Replaying the call (e.g. after a crash) refuses instead of acting again.
    again = await gate.call_tool(ctx, "orchestrator", tool, NOTE, call_id="c1")
    assert again.outcome is ToolOutcome.UNKNOWN
    assert len(effects.sent) == 1


async def test_slow_read_times_out_as_a_failed_result(make_container, tenant_id, user_id):
    container = await make_container()
    ctx = await open_session(container, tenant_id, user_id)
    gate = make_gate(container, stub_registry(SideEffects(), read_delay=1.0), PausingApprovalPort(), timeout_seconds=0.1)

    result = await gate.call_tool(ctx, "orchestrator", "lookup_facts", {"topic": "x"}, call_id="c1")

    assert result.outcome is ToolOutcome.FAILED and "timed out" in (result.error or "")


async def test_ledger_and_approvals_are_tenant_scoped(make_container, tenant_id, user_id):
    container = await make_container()
    ctx = await open_session(container, tenant_id, user_id)
    pausing = PausingApprovalPort()
    with pytest.raises(Paused):
        await make_gate(container, stub_registry(SideEffects()), pausing).call_tool(
            ctx, "orchestrator", "send_note", NOTE, call_id="c1"
        )
    action_id = pausing.requests[0].pending_action_id
    other_tenant = uuid4()

    assert await container.pending_actions.get(tenant_id=other_tenant, action_id=action_id) is None
    assert (
        await container.pending_actions.resolve(
            tenant_id=other_tenant, action_id=action_id, status=PendingActionStatus.APPROVED, resolved_by=user_id
        )
        is None
    )
    assert await container.ledger.list_audit(tenant_id=other_tenant, session_id=ctx.session_id) == []


async def test_only_one_execution_row_per_idempotency_key(make_container, tenant_id, user_id):
    """The partial unique index backs the gate's exactly-once guarantee."""
    container = await make_container()
    ctx = await open_session(container, tenant_id, user_id)
    ledger: LedgerRepository = container.ledger
    fields = AuditFields(
        tenant_id=tenant_id, session_id=ctx.session_id, user_id=user_id, agent="orchestrator", tool="send_note",
        args=NOTE, outcome=ToolOutcome.EXECUTED, idempotency_key="k1",
    )
    await ledger.record(fields)
    with pytest.raises(IntegrityError):
        await ledger.record(fields)
    async with container.engine.connect() as conn:
        count = len((await conn.execute(select(AuditEntry.id).where(AuditEntry.idempotency_key == "k1"))).all())
    assert count == 1


async def test_a_write_whose_arguments_the_preview_rejects_never_asks_for_approval(make_container, tenant_id, user_id):
    from app.tools.adapters.google_calendar import calendar_tools
    from app.tools.registry import ToolRegistry
    from tests.support import FakeConnector

    container = await make_container()
    ctx = await open_session(container, tenant_id, user_id)
    connector = FakeConnector()
    pausing = PausingApprovalPort()
    gate = make_gate(container, ToolRegistry(calendar_tools(connector)), pausing)

    # A wall-clock start with no time zone can't be scheduled: the agent hears it at once.
    result = await gate.call_tool(
        ctx, "orchestrator", "create_calendar_event", {"title": "Demo", "start": "2030-01-01T10:00:00"}, call_id="c1"
    )

    assert result.outcome is ToolOutcome.INVALID and "time_zone" in (result.error or "")
    assert pausing.requests == [] and connector.executions == []
    assert await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id, status=None) == []
    [audit] = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert audit.outcome == "INVALID"


async def test_an_approved_write_runs_with_the_arguments_that_were_approved(make_container, tenant_id, user_id):
    container = await make_container()
    effects = SideEffects()
    ctx = await open_session(container, tenant_id, user_id)
    registry = stub_registry(effects)
    pausing = PausingApprovalPort()
    with pytest.raises(Paused):
        await make_gate(container, registry, pausing).call_tool(ctx, "orchestrator", "send_note", NOTE, call_id="c1")
    await container.pending_actions.resolve(
        tenant_id=tenant_id, action_id=pausing.requests[0].pending_action_id, status=PendingActionStatus.APPROVED,
        resolved_by=user_id,
    )

    # Even if the resumed caller passed different arguments, what runs is what was approved.
    changed = {"to": "someone-else@acme.test", "text": "not what the reviewer saw"}
    result = await make_gate(container, registry, DecidedApprovalPort()).call_tool(
        ctx, "orchestrator", "send_note", changed, call_id="c1"
    )

    assert result.ok and effects.sent[0]["to"] == NOTE["to"] and effects.sent[0]["text"] == NOTE["text"]
