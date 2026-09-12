"""Do the real models actually use the sub-agents? (run with ``pytest --live``)

Nothing is sent: these produce tool-call *requests* only. Free-tier capacity errors skip.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.engine.delegation import DELEGATE_TOOL, RESEARCH_PROMPT, DelegateArgs, delegate_tool
from app.engine.orchestrator import SYSTEM_PROMPT, _clean_schema
from app.models.providers.gemini_provider import GeminiProvider
from app.models.types import Message, ProviderUnavailable, RateLimited, Role, TaskSpec, ToolSpec
from app.tools.adapters.gmail import SearchEmailsArgs, SendEmailArgs
from app.tools.adapters.knowledge import SearchKnowledgeArgs

pytestmark = pytest.mark.live

TODAY = "Today is 2026-09-12 (UTC). The rep's time zone is unknown: ask before scheduling at a clock time."
REQUEST = (
    "Prep me for Acme Corp: what they have been up to recently, what we have said to them before, and which of our "
    "products fit them. Then send their CFO Jane (jane@acme.test) a short intro email using what you find."
)


def _spec(name: str, description: str, model) -> ToolSpec:
    return ToolSpec(name, description, _clean_schema(model.model_json_schema()))


def _tools() -> tuple[ToolSpec, ...]:
    return (
        _spec(DELEGATE_TOOL, delegate_tool().description, DelegateArgs),
        _spec("send_email", "Send an email (the rep approves it first).", SendEmailArgs),
        _spec("search_emails", "Search the rep's email.", SearchEmailsArgs),
        _spec("search_knowledge_base", "Search the workspace knowledge base.", SearchKnowledgeArgs),
    )


async def _complete(provider, task: TaskSpec, models):
    try:
        events = [event async for event in provider.stream(task, models)]
    except (RateLimited, ProviderUnavailable) as exc:
        pytest.skip(f"vendor capacity: {exc}")
    return events[-1].completion


@pytest.fixture(scope="module")
def live_settings() -> Settings:
    return Settings()


async def test_the_model_hands_a_multi_step_request_to_a_sub_agent(live_settings):
    if not live_settings.gemini_api_key:
        pytest.skip("GEMINI_API_KEY not set")
    provider = GeminiProvider(api_key=live_settings.gemini_api_key.get_secret_value(), timeout_seconds=90)

    completion = await _complete(
        provider,
        TaskSpec(
            purpose="live",
            system=SYSTEM_PROMPT.format(time_context=TODAY),
            messages=(Message(role=Role.USER, content=REQUEST),),
            tools=_tools(),
        ),
        (live_settings.model_complex,),
    )

    calls = completion.message.tool_calls
    assert calls, f"the model answered without acting: {completion.message.content[:200]}"
    handed = [call for call in calls if call.name == DELEGATE_TOOL]
    assert handed, f"nothing was delegated; it called {[call.name for call in calls]}"
    for call in handed:
        args = DelegateArgs.model_validate(call.arguments)  # its arguments pass our own validation
        assert args.agent in {"research", "outreach"}
        assert len(args.task) > 30, args.task  # the sub-agent can't see the conversation, so the task must carry it


async def test_a_sub_agent_works_its_task_with_its_own_tools(live_settings):
    if not live_settings.gemini_api_key:
        pytest.skip("GEMINI_API_KEY not set")
    provider = GeminiProvider(api_key=live_settings.gemini_api_key.get_secret_value(), timeout_seconds=90)
    task = "Task: Find out what Acme Corp has been up to recently and what we have said to them before."

    completion = await _complete(
        provider,
        TaskSpec(
            purpose="live",
            system=f"{RESEARCH_PROMPT}\n\n{TODAY}",
            messages=(Message(role=Role.USER, content=task),),
            tools=_tools()[2:],  # what the research sub-agent is allowed: reads only
        ),
        (live_settings.model_complex,),
    )

    called = {call.name for call in completion.message.tool_calls}
    assert called and called <= {"search_emails", "search_knowledge_base"}, called
