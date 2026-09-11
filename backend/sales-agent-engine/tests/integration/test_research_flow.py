"""Phase 2: read tools (no approval) through the orchestrator, gate, stream and snapshot.

The model, Composio, data-pipeline, Tavily and Google grounding are doubles; the engine
itself (HTTP, SSE, LangGraph + checkpointer, gate, audit) is real.
"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

import httpx
import pytest
from pydantic import Field

from app.config import API_PREFIX
from app.container import routing_rules
from app.core.enums import SessionStatus
from app.engine.orchestrator import turn_input
from app.models.router import ModelRouter
from app.models.types import Completion, Message, Role, Source, StreamDone
from app.observability.tracing import NoopTracingClient
from app.platform.data_pipeline import DataPipelineClient
from app.platform.web_search import TavilySearch
from app.tools.adapters.catalog import catalog_tools
from app.tools.adapters.gmail import gmail_tools
from app.tools.adapters.knowledge import knowledge_tools
from app.tools.adapters.web import WebResearch, web_tools
from app.tools.registry import ToolDefinition, ToolRegistry
from app.tools.types import ToolCategory, ToolInput, ToolKind, ToolOutput, ToolScope
from tests.integration.conftest import settle_runs, start_run
from tests.support import FakeConnector, PlanningBrain, make_token, read_sse_until

pytestmark = pytest.mark.integration

EMAILS = {
    "messages": [
        {"messageId": "m1", "threadId": "t1", "messageTimestamp": "1767225600000", "sender": "jane@acme.test",
         "subject": "Re: pricing", "messageText": "Can you match Globex on price?"}
    ]
}


def _data_pipeline() -> DataPipelineClient:
    kv = "/api/v1/knowledge-vault/documents"
    routes = {
        kv: {"documents": [{"doc_id": "doc_battle", "name": "Globex battlecard", "category": "BATTLECARD", "target_competitor": "Globex"}]},
        f"{kv}/doc_battle/content": {"full_text": "Globex charges per seat; we charge per invoice."},
        "/api/v1/catalog/ai/semantic-search": {"results": [{"product_id": "p1", "score": 30, "rationale": "use case"}]},
        "/api/v1/catalog/products/p1": {
            "id": "p1", "name": "Invoicing add-on", "status": "ACTIVE", "min_discount_pct": "0.00", "max_discount_pct": "10.00",
            "variants": [{"sku": "INV-ADD", "price": "49.00", "currency": "USD", "status": "ACTIVE"}],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = routes.get(request.url.path)
        return httpx.Response(200, json=body) if body is not None else httpx.Response(404, json={"detail": "Not found"})

    return DataPipelineClient(base_url="http://data-pipeline.test", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _tavily() -> TavilySearch:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"results": [{"title": "Acme raises Series B", "url": "https://news.test/acme-b", "content": "Acme raised $40M."}]}
        )

    return TavilySearch(api_key="tvly-test", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


class _GroundingBrain:
    name = "gemini"

    async def stream(self, task, models):
        assert task.web_grounded
        message = Message(role=Role.ASSISTANT, content="Acme closed a Series B in August.")
        yield StreamDone(Completion(message=message, provider=self.name, model=models[0], sources=(Source("techcrunch.test", "https://tc.test/acme"),)))


async def test_phase2_done_when_the_agent_answers_a_multi_source_question_streaming_its_steps(
    make_container, serve, rsa_keys, settings, tenant_id, user_id
):
    web_router = ModelRouter({"gemini": _GroundingBrain()}, routing_rules(settings), NoopTracingClient())
    data_pipeline = _data_pipeline()
    registry = ToolRegistry(
        [
            *gmail_tools(FakeConnector(responses={"GMAIL_FETCH_EMAILS": EMAILS})),
            *knowledge_tools(data_pipeline),
            *catalog_tools(data_pipeline),
            *web_tools(WebResearch(router=web_router, tavily=_tavily(), grounding=True), web_router),
        ]
    )
    brain = PlanningBrain(
        [
            ("search_emails", {"query": "from:acme.test"}),
            ("search_knowledge_base", {"query": "Globex pricing"}),
            ("search_catalog", {"query": "invoicing"}),
            ("web_search", {"query": "Acme news"}),
        ]
    )
    container = await make_container(providers={"gemini": brain}, registry=registry)
    base_url = await serve(container)
    token = make_token(rsa_keys, user_id)
    headers = {"Cookie": f"access_token={token}", "X-Tenant-Id": str(tenant_id)}

    async with httpx.AsyncClient(base_url=base_url, timeout=20) as client:
        started = await client.post(f"{API_PREFIX}/chat", headers=headers, json={"message": "Prep me for my Acme call"})
        session_id = started.json()["session_id"]
        events_url = f"{API_PREFIX}/sessions/{session_id}/events"
        events = [e["data"] for e in await read_sse_until(client, events_url, token=token, until={"done", "error"})]
        detail = (await client.get(f"{API_PREFIX}/sessions/{session_id}", headers=headers)).json()

    types = [event["type"] for event in events]
    assert types[-1] == "done" and "awaiting_approval" not in types  # reads never ask for approval
    results = {event["data"]["tool"]: event["data"] for event in events if event["type"] == "tool_result"}
    assert set(results) == {"search_emails", "search_knowledge_base", "search_catalog", "web_search"}
    assert all(result["outcome"] == "EXECUTED" for result in results.values())
    assert [s["url"] for s in results["web_search"]["sources"]] == ["https://tc.test/acme", "https://news.test/acme-b"]

    # One planning step requested all four reads; the next saw every result, in the order requested.
    replies = [m for m in brain.tasks[-1].messages if m.role is Role.TOOL]
    assert [m.name for m in replies] == ["search_emails", "search_knowledge_base", "search_catalog", "web_search"]
    assert '"price": "49.00"' in replies[2].content
    answer = events[-1]["data"]["final_answer"]
    assert "1 email matching" in answer and "1 catalog item matching 'invoicing'" in answer

    assert detail["status"] == "DONE"
    [web_item] = [item for item in detail["transcript"] if item["kind"] == "tool_result" and item["tool"] == "web_search"]
    assert web_item["sources"][0] == {"title": "techcrunch.test", "url": "https://tc.test/acme"}
    audits = await container.ledger.list_audit(tenant_id=tenant_id, session_id=UUID(detail["id"]))
    assert sorted((a.tool, a.outcome) for a in audits) == [
        ("search_catalog", "EXECUTED"), ("search_emails", "EXECUTED"), ("search_knowledge_base", "EXECUTED"), ("web_search", "EXECUTED")
    ]
    assert await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id) == []


class _ProbeArgs(ToolInput):
    label: str = Field(default="probe")


def _meeting_point_reads(barrier: asyncio.Barrier) -> list[ToolDefinition]:
    """Reads that only finish if all of them are running at the same time."""

    async def meet(invocation):
        await asyncio.wait_for(barrier.wait(), timeout=5)
        return ToolOutput(data={"met": True}, summary=f"{invocation.args.label} met the others")

    return [
        ToolDefinition(
            name=f"probe_{letter}", description="probe", kind=ToolKind.READ, scope=ToolScope.READ,
            category=ToolCategory.KNOWLEDGE, input_model=_ProbeArgs, handler=meet,
        )
        for letter in "abc"
    ]


async def test_reads_requested_together_run_concurrently_and_a_write_after_them_still_pauses_alone(
    make_container, tenant_id, user_id
):
    gmail = FakeConnector()
    registry = ToolRegistry([*_meeting_point_reads(asyncio.Barrier(3)), *gmail_tools(gmail)])
    email = {"to": ["jane@acme.test"], "subject": "Hello", "body": "Hi Jane"}
    brain = PlanningBrain([("probe_a", {"label": "a"}), ("probe_b", {"label": "b"}), ("probe_c", {"label": "c"}), ("send_email", email)])
    container = await make_container(providers={"gemini": brain}, registry=registry)

    ctx = await start_run(container, tenant_id, user_id, turn_input("Check and email"), user_message="Check and email")
    await settle_runs(container)

    session = await container.sessions.get(ctx.session_id)
    assert session.status == SessionStatus.AWAITING_APPROVAL and gmail.executions == []
    messages = (await container.runner.snapshot(ctx)).values["messages"]
    replies = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
    assert [r["summary"] for r in replies] == ["a met the others", "b met the others", "c met the others"]
    [pending] = await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id)
    assert pending.tool == "send_email"
