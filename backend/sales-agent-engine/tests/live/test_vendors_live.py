"""Real vendor calls through our adapters (run with ``pytest --live``).

Uses the keys in backend/.env. Nothing is sent or written: model calls only produce
tool-call *requests*, and Composio is only asked whether a connection exists.
Free-tier capacity errors (429/503) skip rather than fail: they are the vendors' state.
"""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from app.config import Settings
from app.engine.orchestrator import _clean_schema
from app.models.providers.gemini_provider import GeminiProvider
from app.models.providers.openrouter_provider import OpenRouterProvider
from app.models.types import (
    Message,
    ProviderUnavailable,
    RateLimited,
    Role,
    StreamDone,
    TaskSpec,
    ToolCall,
    ToolSpec,
)
from app.platform.composio_client import ConnectorClient
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
