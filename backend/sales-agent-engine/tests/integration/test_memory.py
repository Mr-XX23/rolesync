"""Phase 4: context + memory through the real orchestrator, gate, stores and API.

"Done when": a long multi-step run stays within its token budget, and two concurrent writes
don't corrupt memory. The model and workspace-service are doubles; Postgres and Redis are real.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import Field
from sqlalchemy import func, select

from app.config import API_PREFIX
from app.context import stores
from app.context.locks import VersionConflict
from app.context.manager import estimate_task_tokens
from app.core.enums import MemoryScope, SessionStatus
from app.db.models import ContextBlob, MemoryEntry
from app.engine.orchestrator import turn_input
from app.engine.runner import context_for
from app.models.types import Completion, Message, Role, StreamDone, TextDelta, ToolCall, Usage
from app.tools.registry import ToolDefinition, ToolRegistry
from app.tools.types import ToolCategory, ToolInput, ToolInvocation, ToolKind, ToolOutput, ToolScope
from tests.integration.conftest import settle_runs, start_run
from tests.support import make_token

pytestmark = pytest.mark.integration


class ReportArgs(ToolInput):
    topic: str = Field(min_length=1)


def _report_registry() -> ToolRegistry:
    async def big_report(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, ReportArgs)
        body = " ".join(f"{args.topic} fact {index}: revenue grew in region {index}." for index in range(500))
        return ToolOutput(data={"topic": args.topic, "report": body + f" SECRET-CODE-{args.topic.upper()}"}, summary=f"report on {args.topic}")

    return ToolRegistry([
        ToolDefinition(name="big_report", description="A long research report on a topic", kind=ToolKind.READ, scope=ToolScope.READ,
                       category=ToolCategory.KNOWLEDGE, input_model=ReportArgs, handler=big_report),
    ])


class ResearchBrain:
    """Each request: fetch a long report, look inside the stored copy, remember a fact, then answer at length."""

    name = "gemini"

    def __init__(self) -> None:
        self.tasks: list[Any] = []

    async def stream(self, task: Any, models: Any):
        self.tasks.append(task)
        messages = list(task.messages)
        if task.purpose == "summarize-conversation":
            text, calls = "- The rep asked for several regional reports; each was fetched and answered.", []
        else:
            last = messages[-1]
            since_user = messages[max(i for i, m in enumerate(messages) if m.role is Role.USER):]
            done = {m.name for m in since_user if m.role is Role.TOOL}
            topic = next(m.content for m in reversed(messages) if m.role is Role.USER).split()[-1]
            if last.role is Role.USER:
                text, calls = "Fetching the report.", [("big_report", {"topic": topic})]
            elif "read_offloaded_result" not in done:
                report = json.loads(next(m.content for m in since_user if m.name == "big_report"))
                ref = report["offloaded"]["ref"]
                text, calls = "", [("read_offloaded_result", {"ref": ref, "find": "SECRET-CODE"})]
            elif "remember" not in done:
                text, calls = "", [("remember", {"about": "account", "company": "Acme Corp", "fact": f"Acme asked about {topic}"})]
            else:
                text, calls = f"Here is what I found about {topic}. " + "Detailed findings follow. " * 120, []
        if text:
            yield TextDelta(text)
        message = Message(
            role=Role.ASSISTANT,
            content=text,
            tool_calls=tuple(ToolCall(id=f"c{len(self.tasks)}_{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)),
        )
        yield StreamDone(Completion(message=message, provider="gemini", model="scripted", usage=Usage(100, 50)))


async def _wait(container, session_id: UUID, status: SessionStatus, timeout: float = 20.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if (await container.sessions.get(session_id)).status == status:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"session never reached {status}")


async def test_phase4_done_when_a_long_multi_step_run_stays_within_its_token_budget(make_container, tenant_id, user_id, workspace_service):
    workspace_service.profiles[user_id] = {"firstName": "Rohan", "communicationStyle": "Concise", "aiPersonaContext": "I sell to CFOs."}
    brain = ResearchBrain()
    budget = 7_000
    container = await make_container(
        providers={"gemini": brain},
        registry=_report_registry(),
        settings_overrides={"context_budget_tokens": budget, "tool_result_max_chars": 4_000, "context_keep_recent_turns": 1},
    )

    ctx = await start_run(container, tenant_id, user_id, turn_input("Report on north"), user_message="Report on north")
    await settle_runs(container)
    for topic in ("south", "east", "west", "central", "coast"):
        await _wait(container, ctx.session_id, SessionStatus.DONE)
        session = await container.sessions.get(ctx.session_id)
        assert await container.runner.continue_session(session, turn_input(f"Report on {topic}"), user_message=topic) is not None
        await settle_runs(container)
    await _wait(container, ctx.session_id, SessionStatus.DONE)

    plans = [task for task in brain.tasks if task.purpose == "plan"]
    assert len(plans) == 6 * 4
    # Every step fit the budget, although the conversation itself grew far beyond it.
    assert max(estimate_task_tokens(task) for task in plans) <= budget
    history = (await container.runner.snapshot(context_for(await container.sessions.get(ctx.session_id)))).values["messages"]
    transcript_chars = sum(len(json.dumps(message)) for message in history)
    async with container.engine.connect() as conn:
        blobs, blob_chars = (await conn.execute(
            select(func.count(), func.coalesce(func.sum(ContextBlob.chars), 0)).where(ContextBlob.session_id == ctx.session_id)
        )).one()
    assert transcript_chars / 3.5 > budget  # even with large results stored aside, the transcript outgrew the budget
    assert (transcript_chars + blob_chars) / 3.5 > budget * 5  # everything the run read, many times over

    # Older turns were summarized (by the model) and the summary is stored for later steps.
    assert any(task.purpose == "summarize-conversation" for task in brain.tasks)
    summary = await container.memory.latest(tenant_id=tenant_id, scope=MemoryScope.CONVERSATION, key=str(ctx.session_id))
    assert summary is not None and summary.content["through"] > 0 and summary.content["method"] == "model"
    assert "Earlier in this conversation (summary):" in plans[-1].system
    assert "Rep: Rohan" in plans[-1].system and "In their own words: I sell to CFOs." in plans[-1].system

    # Large results were stored once and read back through the reference.
    assert blobs >= 6
    found = [json.loads(m["content"]) for m in history if m.get("name") == "read_offloaded_result"]
    assert len(found) == 6 and all("SECRET-CODE" in result["data"]["passages"][0] for result in found)

    # What was remembered in each request carried over as shared account memory.
    acme = await container.memory.latest(tenant_id=tenant_id, scope=MemoryScope.ACCOUNT, key="acme")
    assert sorted(fact["text"] for fact in acme.content["facts"]) == sorted(
        f"Acme asked about {topic}" for topic in ("north", "south", "east", "west", "central", "coast")
    )


async def test_phase4_done_when_concurrent_writes_do_not_corrupt_memory(make_container, tenant_id, user_id, workspace_service, monkeypatch):
    teammate = uuid4()
    workspace_service.add(teammate, tenant_id)
    container = await make_container()
    conflicts = 0
    retry = stores.with_optimistic_retry

    async def counting_retry(write, **options):
        async def counted():
            nonlocal conflicts
            try:
                return await write()
            except VersionConflict:
                conflicts += 1
                raise

        return await retry(counted, **options)

    monkeypatch.setattr(stores, "with_optimistic_retry", counting_retry)
    mine = context_for(await container.sessions.create(tenant_id=tenant_id, user_id=user_id, mode="INTERACTIVE"))
    theirs = context_for(await container.sessions.create(tenant_id=tenant_id, user_id=teammate, mode="INTERACTIVE"))

    async def remember(ctx, index: int):
        return await container.gate.call_tool(
            ctx, "orchestrator", "remember", {"about": "account", "company": "Acme Corp", "fact": f"Contact number {index} is on the buying committee"},
            call_id=f"r{index}",
        )

    # Two reps' agents save 24 facts about the same customer at the same time.
    results = await asyncio.gather(*(remember(mine if index % 2 else theirs, index) for index in range(24)))

    assert all(result.ok and result.outcome.value == "EXECUTED" for result in results)
    assert conflicts > 0  # the writers really did collide
    record = await container.memory.latest(tenant_id=tenant_id, scope=MemoryScope.ACCOUNT, key="acme")
    assert len(record.content["facts"]) == 24 and len({fact["id"] for fact in record.content["facts"]}) == 24
    assert record.version == 24  # every write built on the one before it; none overwrote another
    assert {fact["saved_by"] for fact in record.content["facts"]} == {str(user_id), str(teammate)}
    async with container.engine.connect() as conn:
        versions = await conn.scalar(select(func.count()).select_from(MemoryEntry).where(MemoryEntry.scope_key == "acme"))
    assert versions <= container.settings.memory_versions_kept  # old versions are pruned
    audits = await container.ledger.list_audit(tenant_id=tenant_id, session_id=mine.session_id)
    assert len(audits) == 12 and {audit.outcome for audit in audits} == {"EXECUTED"}
    assert await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id, status=None) == []  # no approvals


async def test_memory_tools_save_recall_and_forget_without_approval(make_container, tenant_id, user_id, workspace_service):
    viewer = uuid4()
    workspace_service.add(viewer, tenant_id)
    workspace_service.roles[(viewer, tenant_id)] = "VIEWER"
    container = await make_container()
    ctx = context_for(await container.sessions.create(tenant_id=tenant_id, user_id=user_id, mode="INTERACTIVE"))
    gate = container.gate

    saved = await gate.call_tool(ctx, "orchestrator", "remember", {"about": "rep", "fact": "Prefers 30 minute calls"}, call_id="a")
    await gate.call_tool(ctx, "orchestrator", "remember", {"about": "rep", "fact": "prefers 30 minute calls."}, call_id="b")  # duplicate
    recalled = await gate.call_tool(ctx, "orchestrator", "recall", {"about": "rep"}, call_id="c")
    assert saved.ok and [fact["fact"] for fact in recalled.data["facts"]] == ["Prefers 30 minute calls"]

    forgotten = await gate.call_tool(ctx, "orchestrator", "forget", {"about": "rep", "fact_id": saved.data["fact_id"]}, call_id="d")
    assert forgotten.ok and "Forgot about the rep" in forgotten.summary
    assert (await gate.call_tool(ctx, "orchestrator", "recall", {"about": "rep"}, call_id="e")).data["facts"] == []
    missing = await gate.call_tool(ctx, "orchestrator", "forget", {"about": "rep", "fact_id": saved.data["fact_id"]}, call_id="f")
    assert missing.outcome.value == "INVALID"

    viewer_ctx = context_for(await container.sessions.create(tenant_id=tenant_id, user_id=viewer, mode="INTERACTIVE"))
    denied = await gate.call_tool(viewer_ctx, "orchestrator", "remember", {"about": "account", "company": "Acme", "fact": "Budget is 50k"}, call_id="g")
    assert denied.outcome.value == "DENIED"
    own = await gate.call_tool(viewer_ctx, "orchestrator", "remember", {"about": "rep", "fact": "Works mornings"}, call_id="h")
    assert own.ok  # a viewer's own preferences are theirs to keep
    assert (await gate.call_tool(ctx, "research", "remember", {"about": "rep", "fact": "x y z"}, call_id="i")).outcome.value == "DENIED"


async def test_the_memory_api_keeps_rep_memory_private_and_shared_memory_reviewable(make_container, rsa_keys, tenant_id, user_id, workspace_service):
    from app.main import create_app

    viewer, outsider, other_workspace = uuid4(), uuid4(), uuid4()
    workspace_service.add(viewer, tenant_id)
    workspace_service.roles[(viewer, tenant_id)] = "VIEWER"
    workspace_service.add(outsider, other_workspace)
    container = await make_container()
    ctx = context_for(await container.sessions.create(tenant_id=tenant_id, user_id=user_id, mode="INTERACTIVE"))
    await container.gate.call_tool(ctx, "orchestrator", "remember", {"about": "rep", "fact": "Signs off as Rohan"}, call_id="1")
    acme = await container.gate.call_tool(
        ctx, "orchestrator", "remember", {"about": "account", "company": "Acme Corp", "fact": "CFO Jane signs above 20k"}, call_id="2"
    )
    deal_id = uuid4()
    await container.deals.put(user_id, tenant_id, deal_id, {"title": "Acme pilot", "company": "Acme Corp", "stage": "QUALIFIED"})
    await container.gate.call_tool(
        ctx, "orchestrator", "remember", {"about": "deal", "deal_id": str(deal_id), "fact": "Legal review takes two weeks"}, call_id="3"
    )

    app = create_app(container.settings)
    app.state.container = container

    def headers(user: UUID, workspace: UUID) -> dict[str, str]:
        return {"Cookie": f"access_token={make_token(rsa_keys, user)}", "X-Tenant-Id": str(workspace)}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine.test") as client:
        mine = (await client.get(f"{API_PREFIX}/memory/rep", headers=headers(user_id, tenant_id))).json()
        assert [fact["text"] for fact in mine["facts"]] == ["Signs off as Rohan"] and mine["facts"][0]["saved_by_me"]
        theirs = (await client.get(f"{API_PREFIX}/memory/rep", headers=headers(viewer, tenant_id))).json()
        assert theirs["facts"] == []  # private to whoever it is about

        accounts = (await client.get(f"{API_PREFIX}/memory/accounts", headers=headers(viewer, tenant_id))).json()
        assert [(account["key"], account["name"], account["facts"]) for account in accounts] == [("acme", "Acme Corp", 1)]
        def account(company: str, user: UUID = viewer, workspace: UUID = tenant_id):
            return client.get(f"{API_PREFIX}/memory/account", params={"company": company}, headers=headers(user, workspace))

        shared = (await account("ACME, Inc.")).json()  # by the name as written on a deal
        assert shared["key"] == "acme" and shared["facts"][0]["text"] == "CFO Jane signs above 20k"
        assert not shared["facts"][0]["saved_by_me"]
        assert (await account("acme")).json()["facts"] == shared["facts"]  # or by its key
        assert (await account("Globex")).json()["facts"] == []  # nothing known is not an error
        assert (await account(" / ")).status_code == 400
        assert (await client.get(f"{API_PREFIX}/memory/accounts", headers=headers(outsider, other_workspace))).json() == []
        assert (await account("acme", outsider, other_workspace)).json()["facts"] == []

        fact_id = acme.data["fact_id"]
        refused = await client.delete(f"{API_PREFIX}/memory/accounts/acme/facts/{fact_id}", headers=headers(viewer, tenant_id))
        assert refused.status_code == 403
        deleted = await client.delete(f"{API_PREFIX}/memory/accounts/acme/facts/{fact_id}", headers=headers(user_id, tenant_id))
        assert deleted.status_code == 200 and deleted.json()["facts"] == []
        again = await client.delete(f"{API_PREFIX}/memory/accounts/acme/facts/{fact_id}", headers=headers(user_id, tenant_id))
        assert again.status_code == 404
        assert (await client.get(f"{API_PREFIX}/memory/accounts", headers=headers(user_id, tenant_id))).json() == []

        deal = (await client.get(f"{API_PREFIX}/memory/deals/{deal_id}", headers=headers(viewer, tenant_id))).json()
        assert [fact["text"] for fact in deal["facts"]] == ["Legal review takes two weeks"]
        deal_fact = f"{API_PREFIX}/memory/deals/{deal_id}/facts/{deal['facts'][0]['id']}"
        assert (await client.delete(deal_fact, headers=headers(viewer, tenant_id))).status_code == 403
        assert (await client.delete(deal_fact, headers=headers(user_id, tenant_id))).json()["facts"] == []

        rep_fact = f"{API_PREFIX}/memory/rep/facts/{mine['facts'][0]['id']}"
        assert (await client.delete(rep_fact, headers=headers(viewer, tenant_id))).status_code == 404  # not theirs to see
        assert (await client.delete(rep_fact, headers=headers(user_id, tenant_id))).json()["facts"] == []
