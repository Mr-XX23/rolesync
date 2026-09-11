"""Provider translations and router failover (no network)."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.models.providers.gemini_provider import to_contents
from app.models.providers.openrouter_provider import OpenRouterProvider, to_openai_messages
from app.models.router import ModelRouter, Route, RoutingRules
from app.models.types import (
    Complexity,
    Completion,
    Message,
    ProviderError,
    ProviderUnavailable,
    RateLimited,
    Role,
    StreamDone,
    StreamRestart,
    TaskSpec,
    TextDelta,
    ToolCall,
    ToolSpec,
)
from app.observability.tracing import NoopTracingClient

SIGNATURE = base64.b64encode(b"opaque-thought").decode()


def _history() -> tuple[Message, ...]:
    return (
        Message(role=Role.USER, content="Email Jane"),
        Message(
            role=Role.ASSISTANT,
            content="Drafting it now.",
            tool_calls=(
                ToolCall(id="c1", name="send_email", arguments={"to": ["jane@acme.test"]}, signature=SIGNATURE),
                ToolCall(id="c2", name="lookup", arguments={"q": "acme"}),
            ),
        ),
        Message(role=Role.TOOL, content=json.dumps({"ok": True, "outcome": "EXECUTED"}), tool_call_id="c1", name="send_email"),
        Message(role=Role.TOOL, content="plain text result", tool_call_id="c2", name="lookup"),
    )


def test_gemini_history_keeps_signatures_and_groups_tool_results():
    user, model, results = to_contents(_history())
    assert user.role == "user" and user.parts[0].text == "Email Jane"
    assert model.role == "model"
    text, first_call, second_call = model.parts
    assert text.text == "Drafting it now."
    assert first_call.function_call.name == "send_email" and first_call.thought_signature == b"opaque-thought"
    assert second_call.thought_signature is None  # only the first call of a step carries one
    assert results.role == "user" and len(results.parts) == 2  # consecutive tool results → one turn
    assert results.parts[0].function_response.response == {"ok": True, "outcome": "EXECUTED"}
    assert results.parts[1].function_response.response == {"result": "plain text result"}


def test_gemini_history_marks_calls_made_by_another_provider():
    """Gemini 3 rejects replayed function calls without a signature (verified live), so
    calls produced by the OpenRouter failover get Gemini's documented skip marker."""
    history = (
        Message(role=Role.USER, content="hi"),
        Message(role=Role.ASSISTANT, tool_calls=(ToolCall(id="x", name="send_email", arguments={}),)),
    )
    _, model = to_contents(history)
    assert model.parts[0].thought_signature == b"skip_thought_signature_validator"


def test_openai_messages_format():
    task = TaskSpec(purpose="plan", system="be brief", messages=_history())
    messages = to_openai_messages(task)
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool", "tool"]
    call = messages[2]["tool_calls"][0]
    assert call == {"id": "c1", "type": "function", "function": {"name": "send_email", "arguments": '{"to": ["jane@acme.test"]}'}}
    assert messages[3] == {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true, "outcome": "EXECUTED"}'}


def _sse(*chunks: dict | str) -> bytes:
    lines = [": OPENROUTER PROCESSING", ""]
    for chunk in chunks:
        lines += [f"data: {chunk if isinstance(chunk, str) else json.dumps(chunk)}", ""]
    return "\n".join(lines).encode()


async def test_openrouter_streams_text_and_assembles_tool_call_deltas():
    body = _sse(
        {"model": "nvidia/nemotron", "choices": [{"delta": {"content": "Sending "}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call-9", "function": {"name": "send_email", "arguments": '{"to": ["j'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'ane@acme.test"]}'}}]}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 7}},
        "[DONE]",
    )
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        provider = OpenRouterProvider(api_key="k", http=http)
        tools = (ToolSpec("send_email", "send", {"type": "object"}),)
        events = [e async for e in provider.stream(TaskSpec(purpose="p", messages=(), tools=tools), ["m1", "m2"])]

    assert captured["body"]["models"] == ["m1", "m2"] and captured["body"]["stream"] is True
    assert "reasoning" not in captured["body"]  # planning keeps the model's thinking
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Sending "]
    completion = events[-1].completion
    assert completion.model == "nvidia/nemotron" and completion.usage.output_tokens == 7
    assert completion.message.tool_calls == (ToolCall(id="call-9", name="send_email", arguments={"to": ["jane@acme.test"]}),)


def test_citation_markers_are_removed_from_streamed_text():
    from app.models.providers.openrouter_provider import CitationMarkerFilter

    markers = CitationMarkerFilter()
    pieces = ["The plan costs $49 per seat", "【{\"id\": \"doc_3d24\", ", "\"name\": \"pricing.md\"}】", ". Also 【4:0†source】 done 【"]
    streamed = "".join(markers.feed(piece) for piece in pieces) + markers.flush()
    assert streamed == "The plan costs $49 per seat. Also  done 【"  # an unclosed bracket at the end is kept

    long_text = "【" + "x" * 400
    assert CitationMarkerFilter().feed(long_text) == long_text  # not a marker: nothing is swallowed


async def test_openrouter_low_complexity_tasks_turn_reasoning_off():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        chunks = _sse({"model": "m", "choices": [{"delta": {"content": "Brief."}, "finish_reason": "stop"}]}, "[DONE]")
        return httpx.Response(200, content=chunks, headers={"content-type": "text/event-stream"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        provider = OpenRouterProvider(api_key="k", http=http)
        task = TaskSpec(purpose="digest", messages=(), complexity=Complexity.LOW, max_output_tokens=900)
        [*_, done] = [e async for e in provider.stream(task, ["m"])]

    assert captured["body"]["reasoning"] == {"enabled": False} and captured["body"]["max_tokens"] == 900
    assert done.completion.message.content == "Brief."


@pytest.mark.parametrize(("status", "error"), [(429, RateLimited), (503, ProviderUnavailable), (400, ProviderError)])
async def test_openrouter_maps_http_errors(status, error):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, text="nope"))) as http:
        provider = OpenRouterProvider(api_key="k", http=http)
        with pytest.raises(error):
            [e async for e in provider.stream(TaskSpec(purpose="p", messages=()), ["m"])]


# --------------------------------------------------------------------------- router


class FakeProvider:
    def __init__(self, name: str, *, fail_with: Exception | None = None, fail_after_text: bool = False) -> None:
        self.name = name
        self.fail_with = fail_with
        self.fail_after_text = fail_after_text
        self.calls: list[tuple[str, ...]] = []

    async def stream(self, task, models):
        self.calls.append(tuple(models))
        if self.fail_with and not self.fail_after_text:
            raise self.fail_with
        yield TextDelta(f"{self.name} says hi")
        if self.fail_with:
            raise self.fail_with
        yield StreamDone(Completion(Message(role=Role.ASSISTANT, content=f"{self.name} says hi"), provider=self.name, model=models[0]))


RULES = RoutingRules(
    complex=Route("gemini", ("gemini-flash",)),
    simple=Route("openrouter", ("cheap-a", "cheap-b")),
    failover=Route("openrouter", ("strong-free",)),
)


async def _run(router: ModelRouter, complexity: Complexity) -> list:
    return [e async for e in router.stream(TaskSpec(purpose="t", messages=(), complexity=complexity))]


async def test_complex_tasks_use_gemini():
    gemini, openrouter = FakeProvider("gemini"), FakeProvider("openrouter")
    events = await _run(ModelRouter({"gemini": gemini, "openrouter": openrouter}, RULES, NoopTracingClient()), Complexity.HIGH)
    assert events[-1].completion.provider == "gemini" and openrouter.calls == []


async def test_simple_tasks_use_openrouter_with_its_model_list():
    gemini, openrouter = FakeProvider("gemini"), FakeProvider("openrouter")
    events = await _run(ModelRouter({"gemini": gemini, "openrouter": openrouter}, RULES, NoopTracingClient()), Complexity.LOW)
    assert events[-1].completion.provider == "openrouter"
    assert openrouter.calls == [("cheap-a", "cheap-b")] and gemini.calls == []


async def test_gemini_failure_fails_over_to_openrouter_without_failing_the_run():
    gemini = FakeProvider("gemini", fail_with=ProviderUnavailable("503 high demand"))
    openrouter = FakeProvider("openrouter")
    events = await _run(ModelRouter({"gemini": gemini, "openrouter": openrouter}, RULES, NoopTracingClient()), Complexity.HIGH)
    assert events[-1].completion.provider == "openrouter"
    assert openrouter.calls == [("strong-free",)]
    assert not any(isinstance(e, StreamRestart) for e in events)


async def test_mid_stream_failure_tells_consumers_to_discard_partial_text():
    gemini = FakeProvider("gemini", fail_with=RateLimited("429"), fail_after_text=True)
    events = await _run(
        ModelRouter({"gemini": gemini, "openrouter": FakeProvider("openrouter")}, RULES, NoopTracingClient()), Complexity.HIGH
    )
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["TextDelta", "StreamRestart", "TextDelta", "StreamDone"]


async def test_simple_route_failure_is_raised_and_missing_providers_are_skipped():
    router = ModelRouter({"openrouter": FakeProvider("openrouter", fail_with=RateLimited("429"))}, RULES, NoopTracingClient())
    with pytest.raises(RateLimited):
        await _run(router, Complexity.LOW)
    # No Gemini key configured: complex tasks go straight to the failover route.
    only_openrouter = ModelRouter({"openrouter": FakeProvider("openrouter")}, RULES, NoopTracingClient())
    assert (await _run(only_openrouter, Complexity.HIGH))[-1].completion.provider == "openrouter"
    with pytest.raises(ProviderUnavailable):
        await _run(ModelRouter({}, RULES, NoopTracingClient()), Complexity.HIGH)
