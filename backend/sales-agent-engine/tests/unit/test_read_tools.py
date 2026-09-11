"""Phase 2 read tools against canned vendor and data-pipeline responses."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

import httpx
import pytest

from app.core.context import AgentContext, RunMode
from app.models.providers.gemini_provider import _tools as gemini_tools
from app.models.router import ModelRouter, Route, RoutingRules
from app.models.types import (
    Complexity,
    Completion,
    Message,
    ProviderUnavailable,
    RateLimited,
    Role,
    Source,
    StreamDone,
    TaskSpec,
    ToolSpec,
)
from app.observability.tracing import NoopTracingClient
from app.platform.data_pipeline import DataPipelineClient
from app.platform.web_search import TavilySearch
from app.tools.adapters import catalog, gmail, google_calendar, knowledge, notion, slack, web
from app.tools.types import ToolAccessDenied, ToolFailed, ToolInputError, ToolInvocation
from tests.support import FakeConnector

CTX = AgentContext(tenant_id=uuid4(), user_id=uuid4(), session_id=uuid4(), mode=RunMode.INTERACTIVE)


def _tool(definitions, name):
    return next(d for d in definitions if d.name == name)


async def _invoke(definition, **arguments):
    args = definition.input_model.model_validate(arguments)
    if definition.acl is not None:
        await definition.acl(CTX, args)
    return await definition.handler(ToolInvocation(CTX, "orchestrator", "c1", args))


# --------------------------------------------------------------------------- Composio apps


async def test_email_search_is_newest_first_compact_and_uses_gmail_search_syntax():
    connector = FakeConnector(
        responses={
            "GMAIL_FETCH_EMAILS": {
                "messages": [
                    {
                        "messageId": "m1", "threadId": "t1", "messageTimestamp": "1767225600000",
                        "sender": "Jane <jane@acme.com>", "subject": "Pricing", "messageText": "x" * 2_000,
                        "payload": {"parts": ["...base64..."]},
                    },
                    {
                        "messageId": "m2", "threadId": "t2", "messageTimestamp": "1769904000000", "sender": "bob@acme.com",
                        "preview": {"subject": "Renewal", "body": "Let's talk"},
                        "display_url": "https://mail.google.com/mail/u/0/#inbox/m2",
                    },
                ]
            }
        }
    )

    output = await _invoke(_tool(gmail.gmail_tools(connector), "search_emails"), query="from:acme.com", max_results=5)

    [call] = connector.executions
    assert (call["slug"], call["user_id"]) == ("GMAIL_FETCH_EMAILS", CTX.user_id)
    assert call["arguments"] == {"query": "from:acme.com", "max_results": 5, "user_id": "me"}
    newest, older = output.data["emails"]
    assert (newest["message_id"], newest["subject"], newest["text"]) == ("m2", "Renewal", "Let's talk")
    assert len(older["text"]) == 500 and older["text"].endswith("…")
    assert "parts" not in json.dumps(output.data)  # raw payloads never reach the model
    assert [source.url for source in output.sources] == ["https://mail.google.com/mail/u/0/#inbox/m2"]
    assert output.summary == "2 emails matching 'from:acme.com'"


async def test_reading_from_an_app_that_is_not_connected_is_denied_before_any_call():
    connector = FakeConnector(connected={"gmail"})
    with pytest.raises(ToolAccessDenied, match="Slack is not connected"):
        await _invoke(_tool(slack.slack_tools(connector), "search_slack_messages"), query="acme")
    assert connector.executions == []


async def test_calendar_events_default_to_the_next_two_weeks_and_times_go_out_in_utc():
    connector = FakeConnector(
        responses={
            "GOOGLECALENDAR_EVENTS_LIST": {
                "timeZone": "Asia/Kathmandu",
                "items": [
                    {
                        "summary": "Acme demo",
                        "start": {"dateTime": "2026-09-14T10:00:00+05:45"},
                        "end": {"dateTime": "2026-09-14T11:00:00+05:45"},
                        "attendees": [{"email": "jane@acme.com", "displayName": "Jane", "responseStatus": "accepted"}],
                        "description": "d" * 900,
                    },
                    {"start": {"date": "2026-09-20"}, "end": {"date": "2026-09-21"}},
                ],
            }
        }
    )
    list_events = _tool(google_calendar.calendar_tools(connector), "list_calendar_events")

    output = await _invoke(list_events, query="acme")

    sent = connector.executions[0]["arguments"]
    window = datetime.fromisoformat(sent["timeMax"]) - datetime.fromisoformat(sent["timeMin"])
    assert sent["timeMin"].endswith("Z") and window.days == 14
    assert (sent["calendarId"], sent["singleEvents"], sent["orderBy"], sent["q"]) == ("primary", True, "startTime", "acme")
    demo, all_day = output.data["events"]
    assert demo["attendees"] == [{"email": "jane@acme.com", "name": "Jane", "response": "accepted"}]
    assert len(demo["description"]) == 500
    assert (all_day["title"], all_day["start"]) == ("(no title)", "2026-09-20")

    await _invoke(list_events, start="2026-09-14T10:00:00", end="2026-09-15T10:00:00")  # no zone: taken as UTC
    assert connector.executions[-1]["arguments"]["timeMin"] == "2026-09-14T10:00:00Z"
    with pytest.raises(ToolInputError):
        await _invoke(list_events, start="2026-09-14T10:00:00Z", end="2026-09-13T10:00:00Z")


async def test_slack_search_returns_messages_with_channel_and_permalink():
    connector = FakeConnector(
        responses={
            "SLACK_SEARCH_MESSAGES": {
                "ok": True,
                "messages": {
                    "total": 1,
                    "matches": [
                        {
                            "ts": "1767225600", "text": "Acme wants a quote", "username": "jane",
                            "channel": {"id": "C1", "name": "sales"}, "permalink": "https://acme.slack.com/archives/C1/p1",
                        }
                    ],
                },
            }
        }
    )

    output = await _invoke(_tool(slack.slack_tools(connector), "search_slack_messages"), query="acme quote")

    assert output.data["messages"] == [
        {
            "text": "Acme wants a quote", "author": "jane", "channel": "sales",
            "date": "2026-01-01T00:00:00+00:00", "link": "https://acme.slack.com/archives/C1/p1",
        }
    ]
    assert output.sources[0].title == "#sales"


async def test_notion_search_reads_titles_and_pages_come_back_as_bounded_markdown():
    connector = FakeConnector(
        responses={
            "NOTION_SEARCH_NOTION_PAGE": {
                "results": [
                    {
                        "object": "page", "id": "p1", "url": "https://www.notion.so/p1", "last_edited_time": "2026-09-01T00:00:00Z",
                        "properties": {"Name": {"type": "title", "title": [{"plain_text": "Acme "}, {"plain_text": "account plan"}]}},
                    },
                    {"object": "page", "id": "p2", "archived": True, "properties": {}},
                ]
            },
            "NOTION_GET_PAGE_MARKDOWN": {"id": "p1", "markdown": "# Plan\n" + "x" * 20_000, "truncated": False},
        }
    )
    tools = notion.notion_tools(connector)

    found = await _invoke(_tool(tools, "search_notion"), query="acme")
    page = await _invoke(_tool(tools, "read_notion_page"), page_id="0" * 32)

    assert found.data["pages"] == [
        {"page_id": "p1", "title": "Acme account plan", "url": "https://www.notion.so/p1", "last_edited": "2026-09-01T00:00:00Z"}
    ]
    assert page.data["truncated"] is True and len(page.data["markdown"]) == 12_000


# --------------------------------------------------------------------------- data-pipeline


def _data_pipeline(routes: dict[str, object], seen: list[httpx.Request]) -> DataPipelineClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = routes.get(request.url.path)
        if answer is None:
            return httpx.Response(404, json={"detail": "Not found"})
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    return DataPipelineClient(base_url="http://data-pipeline.test", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


_DOCUMENTS = [
    {
        "doc_id": "doc_battle", "name": "Acme vs Globex battlecard", "category": "BATTLECARD", "target_competitor": "Globex",
        "sales_tags": ["pricing"], "sales_summary": "How we beat Globex",
    },
    {"doc_id": "doc_security", "name": "SOC 2 overview", "category": "SECURITY_COMPLIANCE", "sales_summary": "Security posture"},
    {"doc_id": "doc_other", "name": "Holiday schedule", "category": "GENERAL_RESOURCE"},
]
_KV = "/api/v1/knowledge-vault/documents"


def _knowledge_routes() -> dict[str, object]:
    return {
        _KV: {"status": "success", "documents": _DOCUMENTS},
        f"{_KV}/doc_battle/content": {"full_text": "Intro.\n\nGlobex charges per seat, which gets expensive past 50 users."},
        f"{_KV}/doc_security/content": {"full_text": "We are SOC 2 Type II certified."},
        f"{_KV}/doc_other/content": {"full_text": "Office closed for Dashain."},
        f"{_KV}/doc_foreign/content": {"full_text": "someone else's document"},
    }


async def test_knowledge_search_ranks_the_users_documents_and_returns_matching_passages():
    seen: list[httpx.Request] = []
    tools = knowledge.knowledge_tools(_data_pipeline(_knowledge_routes(), seen))

    output = await _invoke(_tool(tools, "search_knowledge_base"), query="How do we win against Globex on pricing?")

    assert [doc["doc_id"] for doc in output.data["documents"]] == ["doc_battle"]  # nothing else matches at all
    assert "Globex charges per seat" in output.data["documents"][0]["passages"][0]
    listing = seen[0]
    assert listing.headers["X-User-Id"] == str(CTX.user_id)
    assert "X-Tenant-Id" not in listing.headers  # vault documents live under data-pipeline's default tenant
    assert (listing.url.params["user_id"], listing.url.params["status"]) == (str(CTX.user_id), "Indexed")


def test_passages_are_the_best_matching_windows_in_document_order():
    filler = "Nothing relevant here. " * 40
    text = "\n\n".join([filler, "Our enterprise pricing starts at 20 seats.", filler, "Pricing for startups is discounted.", filler])

    passages = knowledge.best_passages(text, knowledge.terms("startup pricing"), limit=2)

    assert passages == ["Our enterprise pricing starts at 20 seats.", "Pricing for startups is discounted."]
    assert knowledge.terms("How do we price it for the Acme team?") == ["price", "acme", "team"]


async def test_a_knowledge_document_is_only_read_if_it_belongs_to_the_user():
    seen: list[httpx.Request] = []
    tools = knowledge.knowledge_tools(_data_pipeline(_knowledge_routes(), seen))
    read = _tool(tools, "read_knowledge_document")

    with pytest.raises(ToolAccessDenied):
        await _invoke(read, doc_id="doc_foreign")
    assert not any(request.url.path.endswith("/doc_foreign/content") for request in seen)

    output = await _invoke(read, doc_id="doc_battle")
    assert output.data["text"].startswith("Intro.") and output.data["truncated"] is False


async def test_data_pipeline_failures_are_ordinary_tool_failures():
    tools = knowledge.knowledge_tools(_data_pipeline({_KV: httpx.Response(500, text="boom")}, []))
    with pytest.raises(ToolFailed, match="data-pipeline 500"):
        await _invoke(_tool(tools, "search_knowledge_base"), query="anything at all")


async def test_catalog_search_returns_active_items_with_prices_and_discount_bounds():
    seen: list[httpx.Request] = []
    routes = {
        "/api/v1/catalog/ai/semantic-search": {
            "results": [
                {"product_id": "p-active", "score": 40.0, "rationale": "name match"},
                {"product_id": "p-draft", "score": 30.0},
                {"product_id": "p-gone", "score": 10.0},
            ]
        },
        "/api/v1/catalog/products/p-active": {
            "id": "p-active", "name": "Acme Tee", "type": "PRODUCT", "status": "ACTIVE",
            "min_discount_pct": "0.00", "max_discount_pct": "15.00",
            "options": [{"id": "o1", "name": "Size"}],
            "variants": [
                {"sku": "TEE-L", "price": "19.99", "currency": "USD", "status": "ACTIVE", "option_values": [{"option_id": "o1", "value": "L"}]},
                {"sku": "TEE-XS", "price": "17.99", "currency": "USD", "status": "RETIRED", "option_values": []},
            ],
        },
        "/api/v1/catalog/products/p-draft": {"id": "p-draft", "name": "Prototype", "status": "DRAFT", "variants": []},
    }
    tools = catalog.catalog_tools(_data_pipeline(routes, seen))

    output = await _invoke(_tool(tools, "search_catalog"), query="tee", max_results=5)

    [item] = output.data["items"]
    assert item["variants"] == [{"sku": "TEE-L", "price": "19.99", "currency": "USD", "status": "ACTIVE", "options": {"Size": "L"}}]
    assert item["discount_pct"] == {"min": "0.00", "max": "15.00"}
    assert item["match"] == {"score": 40.0, "why": "name match"}
    search = seen[0]
    assert json.loads(search.content) == {"query": "tee", "limit": 10}
    assert (search.headers["X-Tenant-Id"], search.headers["X-User-Id"]) == (str(CTX.tenant_id), str(CTX.user_id))


async def test_catalog_search_falls_back_to_keyword_matching_on_older_data_pipeline_builds():
    seen: list[httpx.Request] = []
    routes = {  # no semantic-search route: it answers 404
        "/api/v1/catalog/products": [
            {"id": "p1", "name": "Acme Tee", "status": "ACTIVE", "variants": []},
            {"id": "p2", "name": "Old Tee", "status": "RETIRED", "variants": []},
        ]
    }
    tools = catalog.catalog_tools(_data_pipeline(routes, seen))

    output = await _invoke(_tool(tools, "search_catalog"), query="tee", max_results=3)

    assert [item["name"] for item in output.data["items"]] == ["Acme Tee"]
    assert output.data["items"][0]["match"] == {"score": None, "why": "keyword match"}
    listing = seen[-1]
    assert (listing.url.params["keywords"], listing.url.params["limit"]) == ("tee", "6")


async def test_inventory_check_against_a_needed_quantity():
    seen: list[httpx.Request] = []
    routes = {
        "/api/v1/catalog/variants/TEE-L/availability": {
            "sku": "TEE-L", "total_available": 40,
            "by_location": [
                {"location_name": "Kathmandu", "sellable": True, "qty_available": 40},
                {"location_name": "Returns", "sellable": False, "qty_available": 0},
            ],
        }
    }
    tools = catalog.catalog_tools(_data_pipeline(routes, seen))

    output = await _invoke(_tool(tools, "check_inventory"), skus=["TEE-L", "TEE-L", "NOPE"], quantity=50)

    assert sorted(request.url.path for request in seen) == [
        "/api/v1/catalog/variants/NOPE/availability", "/api/v1/catalog/variants/TEE-L/availability"
    ]
    assert output.data["items"] == [
        {"sku": "TEE-L", "found": True, "available": 40, "can_fulfill": False, "locations": [{"location": "Kathmandu", "available": 40}]},
        {"sku": "NOPE", "found": False},
    ]
    assert output.summary == "Stock for 2 SKUs: 0 of 1 can supply 50, 1 not found"


# --------------------------------------------------------------------------- web research


class _Brain:
    def __init__(self, name: str, *, answer: str = "", sources: tuple[Source, ...] = (), fail: Exception | None = None):
        self.name = name
        self.answer = answer
        self.sources = sources
        self.fail = fail
        self.tasks: list[tuple[TaskSpec, tuple[str, ...]]] = []

    async def stream(self, task, models):
        self.tasks.append((task, tuple(models)))
        if self.fail is not None:
            raise self.fail
        message = Message(role=Role.ASSISTANT, content=self.answer)
        yield StreamDone(Completion(message=message, provider=self.name, model=models[0], sources=self.sources))


def _router(**providers) -> ModelRouter:
    rules = RoutingRules(
        complex=Route("gemini", ("gemini-plan",)),
        simple=Route("openrouter", ("cheap",)),
        failover=Route("openrouter", ("backup",)),
        web_grounded=Route("gemini", ("gemini-grounded",)),
    )
    return ModelRouter({name: brain for name, brain in providers.items() if brain}, rules, NoopTracingClient())


def _tavily(results_or_status, seen: list[httpx.Request]) -> TavilySearch:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if isinstance(results_or_status, int):
            return httpx.Response(results_or_status, text="nope")
        return httpx.Response(200, json={"results": results_or_status})

    return TavilySearch(api_key="tvly-test", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


_PAGES = [
    {"title": "Acme raises Series B", "url": "https://news.test/acme-b", "content": "Acme raised $40M.", "published_date": "2026-08-01"},
    {"title": "Acme home", "url": "https://acme.test", "content": "Acme makes billing software."},
]


async def test_web_search_combines_a_google_grounded_answer_with_tavily_pages():
    gemini = _Brain("gemini", answer="Acme makes billing software.", sources=(Source("acme.test", "https://acme.test"),))
    seen: list[httpx.Request] = []
    router = _router(gemini=gemini)
    research = web.WebResearch(router=router, tavily=_tavily(_PAGES, seen), grounding=True)

    output = await _invoke(_tool(web.web_tools(research, router), "web_search"), query="Acme funding", recent_days=90)

    [(task, models)] = gemini.tasks
    assert task.web_grounded and not task.tools and models == ("gemini-grounded",)
    body = json.loads(seen[0].content)
    assert (body["query"], body["max_results"], body["topic"], body["days"]) == ("Acme funding", 5, "news", 90)
    assert seen[0].headers["Authorization"] == "Bearer tvly-test"
    assert output.data["answer"] == "Acme makes billing software."
    assert [r["url"] for r in output.data["results"]] == ["https://news.test/acme-b", "https://acme.test"]
    assert [s.url for s in output.sources] == ["https://acme.test", "https://news.test/acme-b"]  # deduplicated
    assert output.summary == "2 web results for 'Acme funding' and an answer from Google Search"


async def test_web_search_uses_whichever_backend_answers_and_fails_only_if_none_does():
    router = _router(gemini=_Brain("gemini", fail=RateLimited("429 grounding quota")))
    research = web.WebResearch(router=router, tavily=_tavily(_PAGES, []), grounding=True)
    output = await _invoke(_tool(web.web_tools(research, router), "web_search"), query="Acme")
    assert output.data["answer"] is None and len(output.data["results"]) == 2

    broken = web.WebResearch(router=router, tavily=_tavily(401, []), grounding=True)
    with pytest.raises(ToolFailed, match="Tavily 401") as failure:
        await _invoke(_tool(web.web_tools(broken, router), "web_search"), query="Acme")
    assert "429 grounding quota" in str(failure.value)


async def test_prospect_research_is_condensed_by_the_cheap_model_with_numbered_sources():
    gemini = _Brain("gemini", answer="Acme makes billing software for SMBs.", sources=(Source("acme.test", "https://acme.test"),))
    cheap = _Brain("openrouter", answer="Overview: Acme makes billing software [1]. Recent: Series B [2].")
    router = _router(gemini=gemini, openrouter=cheap)
    research = web.WebResearch(router=router, tavily=_tavily(_PAGES, []), grounding=True)
    prospect = _tool(web.web_tools(research, router), "research_prospect")

    output = await _invoke(prospect, company="Acme", person="Jane Doe", focus="our invoicing add-on")

    [(brief_task, models)] = cheap.tasks
    assert brief_task.complexity is Complexity.LOW and models == ("cheap",)
    prompt = brief_task.messages[0].content
    assert "[1] " not in prompt.split("Findings:")[0] and "Rep's focus: our invoicing add-on" in prompt
    assert "[2] Acme raises Series B (2026-08-01): Acme raised $40M." in prompt
    assert len(gemini.tasks) == 1  # one grounded overview; news and the contact come from Tavily only
    assert output.data["brief"].startswith("Overview: Acme makes billing software [1]")
    assert output.data["sources"][:2] == [
        {"n": 1, "title": "acme.test", "url": "https://acme.test"},
        {"n": 2, "title": "Acme raises Series B", "url": "https://news.test/acme-b"},
    ]
    assert "findings" not in output.data

    cheap.fail = ProviderUnavailable("free models busy")
    fallback = await _invoke(prospect, company="Acme")
    assert fallback.data["brief"] is None and fallback.data["findings"][0]["answer"].startswith("Acme makes")
    assert "summary unavailable" in fallback.summary


async def test_without_tavily_prospect_research_asks_google_one_combined_question():
    gemini = _Brain("gemini", answer="Acme makes billing software; Series B in August.", sources=(Source("acme.test", "https://acme.test"),))
    cheap = _Brain("openrouter", answer="Overview: Acme makes billing software [1].")
    router = _router(gemini=gemini, openrouter=cheap)
    research = web.WebResearch(router=router, tavily=None, grounding=True)

    output = await _invoke(_tool(web.web_tools(research, router), "research_prospect"), company="Acme")

    [(task, _)] = gemini.tasks
    assert "most important news of the last six months" in task.messages[0].content
    assert output.data["brief"] == "Overview: Acme makes billing software [1]."
    assert output.data["sources"] == [{"n": 1, "title": "acme.test", "url": "https://acme.test"}]


async def test_an_empty_grounded_answer_is_reported_as_a_failed_search():
    router = _router(gemini=_Brain("gemini", answer="   "))
    research = web.WebResearch(router=router, tavily=None, grounding=True)
    with pytest.raises(ToolFailed, match="Google Search returned no answer"):
        await _invoke(_tool(web.web_tools(research, router), "web_search"), query="Acme")


def test_grounded_tasks_route_only_to_grounding_and_declare_no_tools():
    grounded = TaskSpec(purpose="t", messages=(), web_grounded=True)
    assert _router(gemini=_Brain("gemini")).can_serve(grounded)
    assert not _router(openrouter=_Brain("openrouter")).can_serve(grounded)  # nothing else can ground
    [tool] = gemini_tools(grounded)
    assert tool.google_search is not None and not tool.function_declarations
    with pytest.raises(ValueError):
        TaskSpec(purpose="t", messages=(), web_grounded=True, tools=(ToolSpec("x", "y", {}),))
