"""OpenRouter (OpenAI-compatible chat completions) behind ``LLMProvider``: simple tasks and
Gemini failover. The route's model list is sent as ``models`` so OpenRouter itself falls
through to the next model when one is rate-limited upstream (common on ``:free`` models).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from app.models.types import (
    Completion,
    Complexity,
    Message,
    ProviderError,
    ProviderUnavailable,
    RateLimited,
    Role,
    StreamDone,
    StreamEvent,
    TaskSpec,
    TextDelta,
    ToolCall,
    Usage,
    new_call_id,
)


class OpenRouterProvider:
    name = "openrouter"

    def __init__(
        self,
        *,
        api_key: str,
        http: httpx.AsyncClient,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_seconds: float = 120.0,
    ) -> None:
        self._api_key = api_key
        self._http = http
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._timeout = httpx.Timeout(timeout_seconds, connect=10.0)

    async def stream(self, task: TaskSpec, models: Sequence[str]) -> AsyncIterator[StreamEvent]:
        body: dict[str, Any] = {
            "models": list(models),
            "messages": to_openai_messages(task),
            "stream": True,
            "usage": {"include": True},
        }
        if task.tools:
            body["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in task.tools
            ]
        if task.temperature is not None:
            body["temperature"] = task.temperature
        if task.max_output_tokens:
            body["max_tokens"] = task.max_output_tokens
        if task.complexity is Complexity.LOW:
            # Summaries don't need thinking. On the free reasoning models it used the whole token
            # budget (27s, answer cut off) versus 8s for a complete answer without it (measured).
            body["reasoning"] = {"enabled": False}

        text: list[str] = []
        slots: dict[int, dict[str, Any]] = {}
        markers = CitationMarkerFilter()
        usage = Usage()
        finish_reason: str | None = None
        model_used = models[0]
        headers = {"Authorization": f"Bearer {self._api_key}", "X-Title": "RoleSync Sales Agent Engine"}
        try:
            async with self._http.stream("POST", self._url, headers=headers, json=body, timeout=self._timeout) as response:
                if response.status_code != 200:
                    detail = (await response.aread())[:300].decode("utf-8", errors="replace")
                    raise _error_for(response.status_code, detail)
                async for line in response.aiter_lines():
                    # Blank lines and ": OPENROUTER PROCESSING" keep-alive comments carry no data.
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    if "error" in chunk:
                        error = chunk["error"] or {}
                        raise _error_for(int(error.get("code") or 502), str(error.get("message"))[:300])
                    model_used = chunk.get("model") or model_used
                    if chunk.get("usage"):
                        usage = Usage(
                            input_tokens=int(chunk["usage"].get("prompt_tokens") or 0),
                            output_tokens=int(chunk["usage"].get("completion_tokens") or 0),
                        )
                    for choice in chunk.get("choices") or ():
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            visible = markers.feed(delta["content"])
                            if visible:
                                text.append(visible)
                                yield TextDelta(visible)
                        for part in delta.get("tool_calls") or ():
                            _merge_tool_delta(slots, part)
                        finish_reason = choice.get("finish_reason") or finish_reason
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"openrouter request failed: {type(exc).__name__}") from exc
        rest = markers.flush()
        if rest:
            text.append(rest)
            yield TextDelta(rest)

        calls: list[ToolCall] = []
        for index in sorted(slots):
            slot = slots[index]
            try:
                arguments = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                raise ProviderError(f"openrouter returned malformed arguments for '{slot['name']}'") from exc
            calls.append(
                ToolCall(id=slot["id"] or new_call_id(), name=slot["name"], arguments=arguments if isinstance(arguments, dict) else {})
            )
        if not text and not calls:
            raise ProviderError(f"openrouter returned no content (finish_reason={finish_reason})")
        message = Message(role=Role.ASSISTANT, content="".join(text), tool_calls=tuple(calls))
        yield StreamDone(
            Completion(message=message, provider=self.name, model=model_used, usage=usage, finish_reason=finish_reason)
        )


class CitationMarkerFilter:
    """Removes the citation markers some models emit, like 【{"id": "doc_1"}】 or 【4:0†source】:
    they refer to the model's own training format, not to anything the rep can open. Works on
    streamed text, holding back a possible marker until it closes."""

    _OPEN, _CLOSE, _MAX = "【", "】", 300

    def __init__(self) -> None:
        self._pending = ""

    def feed(self, text: str) -> str:
        data, out = self._pending + text, []
        self._pending = ""
        while (start := data.find(self._OPEN)) >= 0:
            out.append(data[:start])
            end = data.find(self._CLOSE, start)
            if end < 0:
                if len(data) - start > self._MAX:  # too long to be a marker: ordinary text
                    out.append(data[start:])
                else:
                    self._pending = data[start:]
                return "".join(out)
            data = data[end + 1 :]
        out.append(data)
        return "".join(out)

    def flush(self) -> str:
        rest, self._pending = self._pending, ""
        return rest


def to_openai_messages(task: TaskSpec) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if task.system:
        out.append({"role": "system", "content": task.system})
    for message in task.messages:
        if message.role is Role.USER:
            out.append({"role": "user", "content": message.content})
        elif message.role is Role.ASSISTANT:
            item: dict[str, Any] = {"role": "assistant", "content": message.content or None}
            if message.tool_calls:
                item["tool_calls"] = [
                    {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": json.dumps(call.arguments)}}
                    for call in message.tool_calls
                ]
            out.append(item)
        else:
            out.append({"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content})
    return out


def _merge_tool_delta(slots: dict[int, dict[str, Any]], part: dict[str, Any]) -> None:
    slot = slots.setdefault(int(part.get("index", len(slots))), {"id": None, "name": "", "arguments": ""})
    slot["id"] = part.get("id") or slot["id"]
    function = part.get("function") or {}
    name = function.get("name")
    if name and name != slot["name"]:
        # Most models send the name once; some repeat it on every delta.
        slot["name"] = name if not slot["name"] else slot["name"] + name
    slot["arguments"] += function.get("arguments") or ""


def _error_for(status: int, detail: str) -> ProviderError:
    message = f"openrouter {status}: {detail}"
    if status == 429:
        return RateLimited(message)
    if status in (408, 502, 503, 504) or status >= 500:
        return ProviderUnavailable(message)
    return ProviderError(message)
