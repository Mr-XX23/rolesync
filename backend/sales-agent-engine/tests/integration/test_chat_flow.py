"""Phase 1 vertical slice: prompt → orchestrator plans (model router) → streams → gate pauses
on send_email → human approves → resumes → sends → audits → workspace records.

The model and Gmail are doubles (ScriptedBrain, FakeConnector); everything else is real:
FastAPI over HTTP, SSE, LangGraph + Postgres checkpointer, gate, ledger, outbox worker.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import httpx
import pytest

from app.config import API_PREFIX
from app.core.enums import PendingActionStatus, SagaStatus, SessionStatus
from app.engine.orchestrator import turn_input
from app.engine.runner import context_for
from app.engine.workspace_record import context_id_for
from app.models.types import ProviderUnavailable, Role
from app.platform.composio_client import ConnectorOutcomeUnknown
from app.tools.adapters.gmail import gmail_tools
from tests.integration.conftest import all_events, start_run
from tests.support import (
    BlockingBrain,
    FailingBrain,
    FakeConnector,
    ScriptedBrain,
    make_token,
    read_sse_until,
)

pytestmark = pytest.mark.integration


def _headers(rsa_keys, user_id, tenant_id) -> dict[str, str]:
    return {"Cookie": f"access_token={make_token(rsa_keys, user_id)}", "X-Tenant-Id": str(tenant_id)}


async def _wait_for_status(container, session_id, status: SessionStatus, timeout: float = 10.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        row = await container.sessions.get(session_id)
        if row.status == status:
            return row
        await asyncio.sleep(0.05)
    raise AssertionError(f"session {session_id} never reached {status} (is {row.status})")


async def _start(container, tenant_id, user_id, prompt: str = "Email Jane"):
    return await start_run(container, tenant_id, user_id, turn_input(prompt), user_message=prompt)


async def _approve_and_resume(container, ctx, tenant_id, user_id):
    await _wait_for_status(container, ctx.session_id, SessionStatus.AWAITING_APPROVAL)
    [pending] = await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id)
    await container.pending_actions.resolve(
        tenant_id=tenant_id, action_id=pending.id, status=PendingActionStatus.APPROVED, resolved_by=user_id
    )
    await (await container.runner.resume(ctx, {"pending_action_id": str(pending.id)}))


async def test_phase1_done_when_interactive_email_loop_end_to_end(
    make_container, serve, rsa_keys, tenant_id, user_id, workspace_service
):
    brain, gmail = ScriptedBrain(), FakeConnector()
    container = await make_container(providers={"gemini": brain}, registry=_gmail_registry(gmail))
    base_url = await serve(container)
    headers = _headers(rsa_keys, user_id, tenant_id)
    token = make_token(rsa_keys, user_id)

    async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:
        started = await client.post(f"{API_PREFIX}/chat", headers=headers, json={"message": "Email Jane a thank-you for the demo"})
        assert started.status_code == 202, started.text
        session_id = started.json()["session_id"]
        events_url = f"{API_PREFIX}/sessions/{session_id}/events"

        # 1) prompt → plan → stream → gate pauses on the write
        before = await read_sse_until(client, events_url, token=token, until={"awaiting_approval", "error", "done"})
        types = [e["data"]["type"] for e in before]
        assert types[:2] == ["user_message", "step_started"] and "token" in types
        assert before[0]["data"]["data"] == {"text": "Email Jane a thank-you for the demo"}
        assert types[-2:] == ["tool_call", "awaiting_approval"], types
        drafted = "".join(e["data"]["data"].get("text", "") for e in before if e["data"]["type"] == "token")
        assert drafted.strip() == "Drafting the email now."
        approval = before[-1]["data"]["data"]
        assert approval["tool"] == "send_email" and approval["preview"]["subject"] == "Thanks for the demo"
        assert gmail.executions == []

        await _wait_for_status(container, session_id, SessionStatus.AWAITING_APPROVAL)
        detail = (await client.get(f"{API_PREFIX}/sessions/{session_id}", headers=headers)).json()
        assert detail["status"] == "AWAITING_APPROVAL"
        assert [item["kind"] for item in detail["transcript"]] == ["user", "assistant", "tool_call"]
        assert [a["id"] for a in detail["pending_approvals"]] == [approval["pending_action_id"]]
        # The snapshot already contains every streamed step, so a client continues after the last one.
        assert detail["last_event_id"] == before[-1]["id"]

        # 2) human approves → resume → send → answer
        decided = await client.post(
            f"{API_PREFIX}/approvals/{approval['pending_action_id']}/decision", headers=headers, json={"decision": "approve"}
        )
        assert decided.status_code == 200, decided.text
        after = await read_sse_until(
            client, events_url, token=token, until={"done", "error"}, last_event_id=detail["last_event_id"]
        )
        after_types = [e["data"]["type"] for e in after]
        assert after_types[0] == "approval_resolved"
        assert "tool_result" in after_types and after_types[-1] == "done", after_types
        assert after[-1]["data"]["data"]["final_answer"] == "Done: the email to Jane was sent."

        finished = (await client.get(f"{API_PREFIX}/sessions/{session_id}", headers=headers)).json()
        assert finished["status"] == "DONE"
        assert finished["transcript"][-1]["text"] == "Done: the email to Jane was sent."
        replay = await read_sse_until(
            client, events_url, token=token, until={"done"}, last_event_id=finished["last_event_id"]
        )
        assert [e["data"]["type"] for e in replay] == ["done"]  # nothing already in the transcript

    # Gmail was called exactly once, with Composio's argument names, as the session's user.
    [sent] = gmail.executions
    assert sent["slug"] == "GMAIL_SEND_EMAIL" and sent["user_id"] == user_id
    assert sent["arguments"] == {
        "recipient_email": "jane@acme.test",
        "extra_recipients": [],
        "cc": ["cfo@acme.test"],
        "bcc": [],
        "subject": "Thanks for the demo",
        "body": "Hi Jane,\n\nThanks for your time today.\n\nBest,\nRep",
        "is_html": False,
        "user_id": "me",
    }
    # The model's second step saw the executed tool result.
    last_seen = brain.tasks[-1].messages[-1]
    assert last_seen.role is Role.TOOL and '"outcome": "EXECUTED"' in last_seen.content

    session = await container.sessions.get(session_id)
    assert session.status == SessionStatus.DONE
    [audit] = await container.ledger.list_audit(tenant_id=tenant_id, session_id=session.id)
    assert (audit.tool, audit.outcome, audit.agent) == ("send_email", "EXECUTED", "orchestrator")
    [step] = await container.ledger.list_steps(tenant_id=tenant_id, session_id=session.id)
    assert (step.status, step.ref_id) == (SagaStatus.DONE, "gmail-msg-1")

    # Workspace records: the session's context, its email task, the sent email and the answer.
    await container.sync_worker.deliver_due()
    context = workspace_service.contexts[str(context_id_for(session.id))]
    assert context["context_type"] == "AGENT_SESSION" and context["status"] == "DONE"
    assert context["title"] == "Email Jane a thank-you for the demo"
    [task] = workspace_service.tasks.values()
    assert task["task_status"] == "DONE" and task["output_type"] == "EMAIL" and task["agent_name"] == "orchestrator"
    note_titles = sorted(note["note_title"] for note in workspace_service.notes.values())
    assert note_titles == ["Answer: Email Jane a thank-you for the demo", "Sent: Thanks for the demo"]
    statuses = [p["task_status"] for path, p in workspace_service.puts if "/tasks/" in path]
    assert statuses in (["AWAITING_APPROVAL", "DONE"], ["DONE"])  # superseded upserts may be skipped


async def test_a_finished_session_takes_a_follow_up_turn(make_container, rsa_keys, tenant_id, user_id):
    # Gmail is not connected, so every turn ends right after the refused send.
    container = await make_container(
        providers={"gemini": ScriptedBrain()}, registry=_gmail_registry(FakeConnector(connected=False))
    )
    headers = _headers(rsa_keys, user_id, tenant_id)
    async with _asgi_client(container) as client:
        first = (await client.post(f"{API_PREFIX}/chat", headers=headers, json={"message": "Email Jane"})).json()
        session_id = first["session_id"]
        await _wait_for_status(container, session_id, SessionStatus.DONE)

        follow_up = await client.post(
            f"{API_PREFIX}/chat", headers=headers, json={"message": "Try Bob instead", "session_id": session_id}
        )
        assert follow_up.status_code == 202 and follow_up.json()["session_id"] == session_id
        await _wait_for_status(container, session_id, SessionStatus.DONE)
        detail = (await client.get(f"{API_PREFIX}/sessions/{session_id}", headers=headers)).json()

    assert [i["text"] for i in detail["transcript"] if i["kind"] == "user"] == ["Email Jane", "Try Bob instead"]
    events = await all_events(container, session_id)
    assert [e["data"]["text"] for e in events if e["type"] == "user_message"] == ["Email Jane", "Try Bob instead"]
    later = await container.events.read(session_id, after=detail["last_event_id"])
    assert [e.envelope["type"] for e in later] == ["done"]


async def test_paused_run_survives_a_restart_and_resumes_on_approval(make_container, tenant_id, user_id):
    gmail = FakeConnector()
    first = await make_container(providers={"gemini": ScriptedBrain()}, registry=_gmail_registry(gmail))
    ctx = await _start(first, tenant_id, user_id)
    await _wait_for_status(first, ctx.session_id, SessionStatus.AWAITING_APPROVAL)
    [pending] = await first.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id)
    await first.aclose()

    second = await make_container(providers={"gemini": ScriptedBrain()}, registry=_gmail_registry(gmail))
    await second.pending_actions.resolve(
        tenant_id=tenant_id, action_id=pending.id, status=PendingActionStatus.APPROVED, resolved_by=user_id
    )
    await (await second.runner.resume(ctx, {"pending_action_id": str(pending.id)}))

    assert (await second.sessions.get(ctx.session_id)).status == SessionStatus.DONE
    assert len(gmail.executions) == 1
    snapshot = await second.runner.snapshot(ctx)
    assert snapshot.values["final_answer"] == "Done: the email to Jane was sent."


async def test_rejected_email_is_not_sent_and_the_model_asks_what_to_change(make_container, tenant_id, user_id, workspace_service):
    gmail = FakeConnector()
    container = await make_container(providers={"gemini": ScriptedBrain()}, registry=_gmail_registry(gmail))
    ctx = await _start(container, tenant_id, user_id)
    await _wait_for_status(container, ctx.session_id, SessionStatus.AWAITING_APPROVAL)
    [pending] = await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id)

    await container.pending_actions.resolve(
        tenant_id=tenant_id, action_id=pending.id, status=PendingActionStatus.REJECTED, resolved_by=user_id, note="too formal"
    )
    await (await container.runner.resume(ctx, {"pending_action_id": str(pending.id)}))

    assert gmail.executions == []
    snapshot = await container.runner.snapshot(ctx)
    assert snapshot.values["final_answer"] == "Understood, I did not send it. What should I change?"
    await container.sync_worker.deliver_due()
    [task] = workspace_service.tasks.values()
    assert task["task_status"] == "REJECTED"
    assert all(not n["note_title"].startswith("Sent:") for n in workspace_service.notes.values())


async def test_workspace_records_what_was_actually_sent_after_an_edit(make_container, tenant_id, user_id, workspace_service):
    gmail = FakeConnector()
    container = await make_container(providers={"gemini": ScriptedBrain()}, registry=_gmail_registry(gmail))
    ctx = await _start(container, tenant_id, user_id)
    await _wait_for_status(container, ctx.session_id, SessionStatus.AWAITING_APPROVAL)
    [pending] = await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id)

    edited = {**pending.args, "to": ["bob@acme.test"], "subject": "Recap: next steps"}
    await container.pending_actions.resolve(
        tenant_id=tenant_id, action_id=pending.id, status=PendingActionStatus.EDITED, resolved_by=user_id, edited_args=edited
    )
    await (await container.runner.resume(ctx, {"pending_action_id": str(pending.id)}))

    [sent] = gmail.executions
    assert sent["arguments"]["recipient_email"] == "bob@acme.test" and sent["arguments"]["subject"] == "Recap: next steps"
    await container.sync_worker.deliver_due()
    [task] = workspace_service.tasks.values()
    assert task["task_name"] == "Email to bob@acme.test: Recap: next steps" and task["task_status"] == "DONE"
    [note] = [n for n in workspace_service.notes.values() if n["note_title"].startswith("Sent:")]
    assert note["note_title"] == "Sent: Recap: next steps" and note["note_body"].startswith("To: bob@acme.test")


async def test_an_email_whose_send_is_unconfirmed_is_reported_as_unknown_not_failed(
    make_container, tenant_id, user_id, workspace_service
):
    gmail = FakeConnector(fail_with=ConnectorOutcomeUnknown("GMAIL_SEND_EMAIL gave no answer: ReadTimeout"))
    container = await make_container(providers={"gemini": ScriptedBrain()}, registry=_gmail_registry(gmail))
    ctx = await _start(container, tenant_id, user_id)
    await _approve_and_resume(container, ctx, tenant_id, user_id)

    assert (await container.sessions.get(ctx.session_id)).status == SessionStatus.DONE
    assert len(gmail.executions) == 1
    [audit] = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert audit.outcome == "UNKNOWN"
    [step] = await container.ledger.list_steps(tenant_id=tenant_id, session_id=ctx.session_id)
    assert step.status == SagaStatus.PENDING  # a replay of this call is refused instead of sending again
    snapshot = await container.runner.snapshot(ctx)
    assert snapshot.values["final_answer"].startswith("I could not confirm")

    await container.sync_worker.deliver_due()
    [task] = workspace_service.tasks.values()
    assert task["task_status"] == "UNKNOWN"
    assert not any(n["note_title"].startswith("Sent:") for n in workspace_service.notes.values())


async def test_malformed_arguments_from_the_model_are_refused_without_breaking_the_run(
    make_container, tenant_id, user_id, workspace_service
):
    gmail = FakeConnector()
    brain = ScriptedBrain(email={"to": "jane@acme.test", "subject": 42, "body": "hi"})
    container = await make_container(providers={"gemini": brain}, registry=_gmail_registry(gmail))
    ctx = await _start(container, tenant_id, user_id)
    await _wait_for_status(container, ctx.session_id, SessionStatus.DONE)

    assert gmail.executions == []
    assert (await container.runner.snapshot(ctx)).values["final_answer"] == "The email was not sent (INVALID)."
    await container.sync_worker.deliver_due()
    [task] = workspace_service.tasks.values()
    assert (task["task_name"], task["task_status"]) == ("Email to jane@acme.test:", "FAILED")


async def test_a_crash_inside_a_tool_call_is_reported_to_the_model_instead_of_failing_the_run(
    make_container, tenant_id, user_id
):
    gmail = FakeConnector()
    container = await make_container(providers={"gemini": ScriptedBrain()}, registry=_gmail_registry(gmail))

    async def crash(*args, **kwargs):
        raise RuntimeError("ledger connection reset")

    container.gate.call_tool = crash
    ctx = await _start(container, tenant_id, user_id)
    await _wait_for_status(container, ctx.session_id, SessionStatus.DONE)

    values = (await container.runner.snapshot(ctx)).values
    assert values["final_answer"] == "The email was not sent (FAILED)."
    reply = values["messages"][-2]
    assert reply["role"] == "tool" and "may not have completed" in reply["content"]
    assert gmail.executions == []


async def test_gmail_not_connected_is_refused_before_any_approval_is_requested(make_container, tenant_id, user_id):
    gmail = FakeConnector(connected=False)
    container = await make_container(providers={"gemini": ScriptedBrain()}, registry=_gmail_registry(gmail))

    ctx = await _start(container, tenant_id, user_id)
    await _wait_for_status(container, ctx.session_id, SessionStatus.DONE)

    assert await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id) == []
    snapshot = await container.runner.snapshot(ctx)
    assert snapshot.values["final_answer"] == "The email was not sent (DENIED)."
    [audit] = await container.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert audit.outcome == "DENIED" and "Gmail is not connected" in audit.result_summary


async def test_gemini_outage_fails_over_to_openrouter(make_container, tenant_id, user_id):
    gemini = FailingBrain("gemini", ProviderUnavailable("503 high demand"))
    openrouter = ScriptedBrain("openrouter")
    container = await make_container(
        providers={"gemini": gemini, "openrouter": openrouter}, registry=_gmail_registry(FakeConnector())
    )

    ctx = await _start(container, tenant_id, user_id)
    await _wait_for_status(container, ctx.session_id, SessionStatus.AWAITING_APPROVAL)

    assert gemini.calls == 1 and len(openrouter.tasks) == 1


async def test_busy_session_and_workspace_run_budget(make_container, rsa_keys, tenant_id, user_id):
    container = await make_container(
        providers={"gemini": ScriptedBrain()},
        registry=_gmail_registry(FakeConnector()),
        settings_overrides={"max_concurrent_runs_per_tenant": 1},
    )
    headers = _headers(rsa_keys, user_id, tenant_id)
    app_client = _asgi_client(container)
    async with app_client as client:
        first = (await client.post(f"{API_PREFIX}/chat", headers=headers, json={"message": "Email Jane"})).json()
        await _wait_for_status(container, first["session_id"], SessionStatus.AWAITING_APPROVAL)

        busy = await client.post(
            f"{API_PREFIX}/chat", headers=headers, json={"message": "and Bob", "session_id": first["session_id"]}
        )
        assert busy.status_code == 409

        stuck = await container.sessions.create(tenant_id=tenant_id, user_id=user_id, mode=ctx_mode(), title="running")
        over_budget = await client.post(f"{API_PREFIX}/chat", headers=headers, json={"message": "one more"})
        assert over_budget.status_code == 429 and over_budget.json()["code"] == "BUDGET_EXCEEDED"
        await container.sessions.transition(stuck.id, to=SessionStatus.FAILED)

        other = await client.post(
            f"{API_PREFIX}/chat",
            headers=_headers(rsa_keys, user_id, tenant_id),
            json={"message": "hi", "session_id": str(uuid4())},
        )
        assert other.status_code == 404


async def test_a_run_whose_process_died_is_recovered_from_its_checkpoint(make_container, tenant_id, user_id):
    blocking = BlockingBrain()
    crashed = await make_container(providers={"gemini": blocking}, registry=_gmail_registry(FakeConnector()))
    ctx = await _start(crashed, tenant_id, user_id)
    await asyncio.wait_for(blocking.started.wait(), 10)
    await crashed.aclose()  # the process stops mid-step; the session is still RUNNING
    assert (await crashed.sessions.get(ctx.session_id)).status == SessionStatus.RUNNING

    restarted = await make_container(providers={"gemini": ScriptedBrain()}, registry=_gmail_registry(FakeConnector()))
    recovered = await restarted.runner.recover_orphans()

    assert recovered == [ctx.session_id]
    await _wait_for_status(restarted, ctx.session_id, SessionStatus.AWAITING_APPROVAL)
    assert await restarted.runner.recover_orphans() == []  # paused sessions are not orphans
    row = await restarted.sessions.get(ctx.session_id)
    assert context_for(row).session_id == ctx.session_id


async def test_workspace_outbox_retries_in_order_and_gives_up_on_rejections(
    make_container, tenant_id, user_id, workspace_service
):
    container = await make_container(providers={"gemini": ScriptedBrain()}, registry=_gmail_registry(FakeConnector()))
    ctx = await _session(container, tenant_id, user_id)
    await container.recorder.session_updated(ctx, title="Outreach", status=SessionStatus.RUNNING)
    await container.recorder.answer_recorded(ctx, turn=1, prompt="hi", answer="hello")

    workspace_service.fail_next_puts = [503]  # the context upsert fails transiently
    assert await container.sync_worker.deliver_due() == 0
    rows = await container.outbox.list_for_session(ctx.session_id)
    assert [(r.kind, r.status, r.attempts) for r in rows] == [("CONTEXT", "PENDING", 1), ("NOTE", "PENDING", 0)]
    assert workspace_service.contexts == {} and workspace_service.notes == {}  # the note waited behind it

    await _skip_backoff(container)
    assert await container.sync_worker.deliver_due() == 2
    assert len(workspace_service.notes) == 1

    # A permanent rejection (e.g. membership revoked) is recorded, not retried forever.
    workspace_service.fail_next_puts = [403]
    await container.recorder.session_updated(ctx, title="Outreach", status=SessionStatus.DONE)
    await container.sync_worker.deliver_due()
    last = (await container.outbox.list_for_session(ctx.session_id))[-1]
    assert last.status == "FAILED" and "403" in (last.last_error or "")


async def test_a_session_waiting_out_a_backoff_does_not_hold_up_other_sessions(
    make_container, tenant_id, user_id, workspace_service
):
    container = await make_container()
    slow = await _session(container, tenant_id, user_id)
    fine = await _session(container, tenant_id, user_id)
    await container.recorder.session_updated(slow, title="slow", status=SessionStatus.RUNNING)
    await container.recorder.answer_recorded(slow, turn=1, prompt="hi", answer="hello")  # due, but behind its head
    await container.recorder.session_updated(fine, title="fine", status=SessionStatus.RUNNING)

    workspace_service.fail_next_puts = [503]  # the first session's context is refused once, then backs off
    await container.sync_worker.deliver_due()

    # The slow session only has records that must wait for its head, so it is not "due" at all.
    assert await container.outbox.due_sessions() == []
    assert list(workspace_service.contexts) == [str(context_id_for(fine.session_id))]


async def test_a_record_whose_context_never_arrives_stops_blocking_the_session(
    make_container, tenant_id, user_id, workspace_service
):
    from app.db.repositories.outbox import MAX_NOT_FOUND_ATTEMPTS

    container = await make_container()
    ctx = await _session(container, tenant_id, user_id)
    # A note enqueued without its context (as if the context upsert had been rejected earlier).
    await container.recorder.answer_recorded(ctx, turn=1, prompt="hi", answer="hello")
    await container.recorder.session_updated(ctx, title="later", status=SessionStatus.DONE)

    for _ in range(MAX_NOT_FOUND_ATTEMPTS):
        await container.sync_worker.deliver_due()
        await _skip_backoff(container)

    rows = await container.outbox.list_for_session(ctx.session_id)
    assert [(r.kind, r.status) for r in rows] == [("NOTE", "FAILED"), ("CONTEXT", "DELIVERED")]
    assert rows[0].attempts == MAX_NOT_FOUND_ATTEMPTS and "404" in (rows[0].last_error or "")


async def test_each_delivered_record_is_saved_even_if_a_later_one_crashes(make_container, tenant_id, user_id):
    from app.platform.workspace_client import Delivery, DeliveryResult

    container = await make_container()
    ctx = await _session(container, tenant_id, user_id)
    await container.recorder.session_updated(ctx, title="one", status=SessionStatus.RUNNING)
    await container.recorder.answer_recorded(ctx, turn=1, prompt="hi", answer="hello")

    async def deliver_then_crash(item):
        if item.kind == "NOTE":
            raise RuntimeError("worker died mid-batch")
        return Delivery(DeliveryResult.DELIVERED, "ok")

    with pytest.raises(RuntimeError):
        await container.outbox.deliver_session(ctx.session_id, deliver_then_crash, max_attempts=5)

    rows = await container.outbox.list_for_session(ctx.session_id)
    assert [(r.kind, r.status) for r in rows] == [("CONTEXT", "DELIVERED"), ("NOTE", "PENDING")]
    # The advisory lock was released, so the next pass can deliver the rest.
    assert await container.outbox.deliver_session(ctx.session_id, _always_delivered, max_attempts=5) == 1


async def _always_delivered(item):
    from app.platform.workspace_client import Delivery, DeliveryResult

    return Delivery(DeliveryResult.DELIVERED, "ok")


async def _session(container, tenant_id, user_id):
    from tests.integration.conftest import open_session

    return await open_session(container, tenant_id, user_id)


async def _skip_backoff(container) -> None:
    from sqlalchemy import update

    from app.db.models import WorkspaceOutbox

    async with container.engine.begin() as conn:
        await conn.execute(update(WorkspaceOutbox).values(next_attempt_at=WorkspaceOutbox.created_at))


def _gmail_registry(connector: FakeConnector):
    from app.tools.registry import ToolRegistry

    return ToolRegistry(gmail_tools(connector))


def _asgi_client(container) -> httpx.AsyncClient:
    from app.main import create_app

    app = create_app(container.settings)
    app.state.container = container
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine.test")


def ctx_mode():
    from app.core.context import RunMode

    return RunMode.INTERACTIVE
