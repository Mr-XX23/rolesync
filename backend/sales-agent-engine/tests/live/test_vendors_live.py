"""Real vendor calls through our adapters (run with ``pytest --live``).

Uses the keys in backend/.env. Nothing is sent or written: model calls only produce
tool-call *requests*, and Composio is only asked whether a connection exists.
Free-tier capacity errors (429/503) skip rather than fail: they are the vendors' state.
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from app.config import Settings
from app.container import routing_rules
from app.engine.orchestrator import _clean_schema
from app.models.providers.gemini_provider import GeminiProvider
from app.models.providers.openrouter_provider import OpenRouterProvider
from app.models.router import ModelRouter
from app.models.types import (
    Complexity,
    Message,
    ProviderUnavailable,
    RateLimited,
    Role,
    StreamDone,
    TaskSpec,
    ToolCall,
    ToolSpec,
)
from app.observability.tracing import NoopTracingClient
from app.platform.composio_client import ConnectorClient
from app.platform.web_search import TavilySearch
from app.tools.adapters.gmail import SendEmailArgs

pytestmark = pytest.mark.live

PROMPT = "Email jane@acme.test a two-sentence thank-you for today's product demo. Use the tool."
SYSTEM = "You are a sales assistant. Act through tools; the user approves emails before they are sent."


@pytest.fixture(scope="module")
def live_settings() -> Settings:
    return Settings()


def _send_email_spec() -> ToolSpec:
    return ToolSpec("send_email", "Send an email (user approves first).", _clean_schema(SendEmailArgs.model_json_schema()))


async def _complete(provider, task: TaskSpec, models) -> StreamDone:
    try:
        events = [event async for event in provider.stream(task, models)]
    except (RateLimited, ProviderUnavailable) as exc:
        pytest.skip(f"vendor capacity: {exc}")
    return events[-1]


async def test_gemini_calls_send_email_and_accepts_its_own_and_foreign_history(live_settings):
    if not live_settings.gemini_api_key:
        pytest.skip("GEMINI_API_KEY not set")
    provider = GeminiProvider(api_key=live_settings.gemini_api_key.get_secret_value(), timeout_seconds=90)
    models = (live_settings.model_complex,)
    user = Message(role=Role.USER, content=PROMPT)

    first = await _complete(provider, TaskSpec(purpose="live", system=SYSTEM, messages=(user,), tools=(_send_email_spec(),)), models)
    [call] = first.completion.message.tool_calls
    assert call.name == "send_email" and "jane@acme.test" in call.arguments["to"]
    SendEmailArgs.model_validate(call.arguments)  # the model's arguments pass our own validation

    result = Message(role=Role.TOOL, content=json.dumps({"ok": True, "outcome": "EXECUTED"}), tool_call_id=call.id, name=call.name)
    own = await _complete(
        provider, TaskSpec(purpose="live", system=SYSTEM, messages=(user, first.completion.message, result), tools=(_send_email_spec(),)), models
    )
    assert own.completion.message.content

    # The same history as if the call had come from the OpenRouter failover (no signature).
    foreign_call = Message(role=Role.ASSISTANT, tool_calls=(ToolCall(id=call.id, name=call.name, arguments=call.arguments),))
    foreign = await _complete(
        provider, TaskSpec(purpose="live", system=SYSTEM, messages=(user, foreign_call, result), tools=(_send_email_spec(),)), models
    )
    assert foreign.completion.message.content


async def test_openrouter_failover_models_call_send_email(live_settings):
    if not live_settings.openrouter_api_key:
        pytest.skip("OPEN_ROUTER_API not set")
    async with httpx.AsyncClient() as http:
        provider = OpenRouterProvider(api_key=live_settings.openrouter_api_key.get_secret_value(), http=http, timeout_seconds=90)
        done = await _complete(
            provider,
            TaskSpec(purpose="live", system=SYSTEM, messages=(Message(role=Role.USER, content=PROMPT),), tools=(_send_email_spec(),)),
            live_settings.split_list(live_settings.models_failover),
        )
    message = done.completion.message
    assert message.tool_calls or message.content
    if message.tool_calls:
        assert message.tool_calls[0].name == "send_email"


async def test_composio_connection_lookup_is_read_only_and_answers(live_settings):
    if not live_settings.composio_api_key:
        pytest.skip("COMPOSIO_API_KEY not set")
    connector = ConnectorClient(
        api_key=live_settings.composio_api_key.get_secret_value(), toolkit_versions=live_settings.composio_versions()
    )
    assert await connector.has_active_connection(uuid4(), "gmail") is False


# The argument names each adapter sends, by Composio action.
ADAPTER_ARGUMENTS = {
    "GMAIL_SEND_EMAIL": {"recipient_email", "extra_recipients", "cc", "bcc", "subject", "body", "is_html", "user_id"},
    "GMAIL_FETCH_EMAILS": {"query", "max_results", "user_id"},
    "GMAIL_FETCH_MESSAGE_BY_THREAD_ID": {"thread_id", "user_id"},
    "GOOGLECALENDAR_EVENTS_LIST": {"calendarId", "timeMin", "timeMax", "singleEvents", "orderBy", "maxResults", "q"},
    "SLACK_SEARCH_MESSAGES": {"query", "count", "sort", "sort_dir"},
    "NOTION_SEARCH_NOTION_PAGE": {"query", "page_size"},
    "NOTION_GET_PAGE_MARKDOWN": {"page_id"},
}


async def test_composio_actions_accept_the_arguments_our_adapters_send(live_settings):
    """Reads tool schemas only (no account is touched), so a renamed argument fails here, not in a chat."""
    if not live_settings.composio_api_key:
        pytest.skip("COMPOSIO_API_KEY not set")
    from composio import Composio

    pins = live_settings.composio_versions()
    sdk = Composio(api_key=live_settings.composio_api_key.get_secret_value(), toolkit_versions=pins)
    for slug, arguments in ADAPTER_ARGUMENTS.items():
        assert slug.split("_", 1)[0].lower() in pins, f"{slug}: toolkit version not pinned"
        tool = await asyncio.to_thread(sdk.tools.get_raw_composio_tool_by_slug, slug)
        accepted = set((tool.input_parameters or {}).get("properties") or {})
        assert arguments <= accepted, f"{slug} no longer accepts {sorted(arguments - accepted)}"


async def test_gemini_answers_a_web_grounded_task_with_sources(live_settings):
    if not live_settings.gemini_api_key:
        pytest.skip("GEMINI_API_KEY not set")
    provider = GeminiProvider(api_key=live_settings.gemini_api_key.get_secret_value(), timeout_seconds=90)
    router = ModelRouter({"gemini": provider}, routing_rules(live_settings), NoopTracingClient())
    task = TaskSpec(
        purpose="live",
        messages=(Message(role=Role.USER, content="What is the latest stable release of Python? One sentence."),),
        web_grounded=True,
    )
    try:
        completion = await router.complete(task)
    except (RateLimited, ProviderUnavailable) as exc:
        pytest.skip(f"vendor capacity: {exc}")
    assert completion.message.content and completion.model == live_settings.model_web_grounding
    assert completion.sources and all(source.url.startswith("https://") for source in completion.sources)


async def test_tavily_returns_pages(live_settings):
    if not live_settings.tavily_api_key:
        pytest.skip("TAVILY_API_KEY not set")
    async with httpx.AsyncClient() as http:
        pages = await TavilySearch(api_key=live_settings.tavily_api_key.get_secret_value(), http=http).search(
            "latest stable Python release", max_results=3
        )
    assert pages and all(page.url.startswith("http") for page in pages)


RESEARCH_PROMPT = (
    "I have a call with Acme Corp tomorrow. Check our past emails with acme.com, what our knowledge base says "
    "about competing with Globex, which catalog products fit an invoicing need, and recent Acme news."
)


def _full_registry(settings: Settings, http: httpx.AsyncClient):
    """Every tool the engine registers in production (nothing here gets executed)."""
    from app.container import default_registry
    from tests.support import FakeConnector

    router = ModelRouter({"gemini": object()}, routing_rules(settings), NoopTracingClient())  # never called
    registry = default_registry(settings, connector=FakeConnector(), router=router, http=http)
    specs = tuple(ToolSpec(d.name, d.description, _clean_schema(d.parameters_schema())) for d in registry.all())
    return registry, specs


async def test_gemini_accepts_every_tool_schema_and_plans_parallel_reads(live_settings):
    if not live_settings.gemini_api_key:
        pytest.skip("GEMINI_API_KEY not set")
    async with httpx.AsyncClient() as http:
        registry, specs = _full_registry(live_settings, http)
        provider = GeminiProvider(api_key=live_settings.gemini_api_key.get_secret_value(), timeout_seconds=90)
        task = TaskSpec(purpose="live", system=SYSTEM, messages=(Message(role=Role.USER, content=RESEARCH_PROMPT),), tools=specs)
        done = await _complete(provider, task, (live_settings.model_complex,))
    calls = done.completion.message.tool_calls
    assert len(calls) >= 2, f"expected several reads in one step, got {calls or done.completion.message.content!r}"
    for call in calls:
        definition = registry.get(call.name)
        assert definition is not None and definition.kind.value == "READ", call.name
        definition.input_model.model_validate(call.arguments)  # the model's arguments pass our validation


async def test_openrouter_failover_accepts_every_tool_schema(live_settings):
    if not live_settings.openrouter_api_key:
        pytest.skip("OPEN_ROUTER_API not set")
    async with httpx.AsyncClient() as http:
        _, specs = _full_registry(live_settings, http)
        provider = OpenRouterProvider(api_key=live_settings.openrouter_api_key.get_secret_value(), http=http, timeout_seconds=90)
        task = TaskSpec(purpose="live", system=SYSTEM, messages=(Message(role=Role.USER, content=RESEARCH_PROMPT),), tools=specs)
        done = await _complete(provider, task, live_settings.split_list(live_settings.models_failover))
    assert done.completion.message.tool_calls or done.completion.message.content  # accepted, whatever it chose


async def test_openrouter_serves_low_complexity_digests(live_settings):
    if not live_settings.openrouter_api_key:
        pytest.skip("OPEN_ROUTER_API not set")
    async with httpx.AsyncClient() as http:
        provider = OpenRouterProvider(api_key=live_settings.openrouter_api_key.get_secret_value(), http=http, timeout_seconds=90)
        router = ModelRouter({"openrouter": provider}, routing_rules(live_settings), NoopTracingClient())
        task = TaskSpec(
            purpose="live",
            messages=(Message(role=Role.USER, content="Summarize in one sentence: [1] Acme sells billing software to SMBs."),),
            complexity=Complexity.LOW,
            max_output_tokens=200,
        )
        try:
            completion = await router.complete(task)
        except (RateLimited, ProviderUnavailable) as exc:
            pytest.skip(f"vendor capacity: {exc}")
    assert completion.provider == "openrouter" and completion.message.content
