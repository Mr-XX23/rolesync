"""Gemini (``google-genai``) behind ``LLMProvider``: the primary model for complex reasoning.

Thought signatures: Gemini 3 attaches an opaque signature to its function-call parts and
rejects a later request whose history replays a function call without one (HTTP 400,
verified). Signatures ride along in ``ToolCall.signature``. Calls produced by another
provider (after a failover) carry none, so the first call of such a turn gets Gemini's
documented ``skip_thought_signature_validator`` marker instead.
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

from app.models.types import (
    Completion,
    Message,
    ProviderError,
    ProviderUnavailable,
    RateLimited,
    Role,
    Source,
    StreamDone,
    StreamEvent,
    TaskSpec,
    TextDelta,
    ToolCall,
    Usage,
    new_call_id,
)

_SKIP_SIGNATURE = b"skip_thought_signature_validator"


class GeminiProvider:
    name = "gemini"

    def __init__(self, *, api_key: str, timeout_seconds: float) -> None:
        # No SDK-level retries: a failing call should reach the router's failover quickly.
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000))
        )

    async def stream(self, task: TaskSpec, models: Sequence[str]) -> AsyncIterator[StreamEvent]:
        model = models[0]
        config = types.GenerateContentConfig(
            system_instruction=task.system,
            tools=_tools(task),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=task.temperature,
            max_output_tokens=task.max_output_tokens,
        )
        text: list[str] = []
        text_signature: str | None = None
        calls: list[ToolCall] = []
        sources: dict[str, Source] = {}
        usage = Usage()
        finish_reason: str | None = None
        try:
            response_stream = await self._client.aio.models.generate_content_stream(
                model=model, contents=to_contents(task.messages), config=config
            )
            async for chunk in response_stream:
                if chunk.usage_metadata is not None:
                    meta = chunk.usage_metadata
                    usage = Usage(
                        input_tokens=meta.prompt_token_count or 0,
                        output_tokens=(meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0),
                    )
                for candidate in chunk.candidates or ():
                    if candidate.finish_reason is not None:
                        finish_reason = str(getattr(candidate.finish_reason, "value", candidate.finish_reason))
                    grounding = candidate.grounding_metadata
                    for grounding_chunk in (grounding.grounding_chunks or ()) if grounding else ():
                        web = grounding_chunk.web
                        if web is not None and web.uri:
                            sources.setdefault(web.uri, Source(title=web.title or web.domain or web.uri, url=web.uri))
                    parts = candidate.content.parts if candidate.content and candidate.content.parts else ()
                    for part in parts:
                        if part.function_call is not None:
                            call = part.function_call
                            calls.append(
                                ToolCall(
                                    id=call.id or new_call_id(),
                                    name=call.name or "",
                                    arguments=dict(call.args or {}),
                                    signature=_encode(part.thought_signature),
                                )
                            )
                        elif part.thought:
                            continue  # never surface the model's private reasoning
                        else:
                            if part.text:
                                text.append(part.text)
                                yield TextDelta(part.text)
                            if part.thought_signature and text_signature is None:
                                text_signature = _encode(part.thought_signature)
        except errors.APIError as exc:
            raise _map_api_error(exc) from exc
        except (httpx.HTTPError, TimeoutError, OSError) as exc:
            raise ProviderUnavailable(f"gemini request failed: {type(exc).__name__}") from exc

        if not text and not calls:
            raise ProviderError(f"gemini returned no content (finish_reason={finish_reason})")
        message = Message(role=Role.ASSISTANT, content="".join(text), tool_calls=tuple(calls), signature=text_signature)
        yield StreamDone(
            Completion(
                message=message,
                provider=self.name,
                model=model,
                usage=usage,
                finish_reason=finish_reason,
                sources=tuple(sources.values()),
            )
        )


def to_contents(messages: Sequence[Message]) -> list[types.Content]:
    """Neutral history → Gemini contents. Consecutive tool results become one user turn."""
    contents: list[types.Content] = []
    responses: list[types.Part] = []

    def flush_responses() -> None:
        if responses:
            contents.append(types.Content(role="user", parts=list(responses)))
            responses.clear()

    for message in messages:
        if message.role is Role.TOOL:
            responses.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        id=message.tool_call_id, name=message.name or "tool", response=_as_object(message.content)
                    )
                )
            )
            continue
        flush_responses()
        if message.role is Role.USER:
            contents.append(types.Content(role="user", parts=[types.Part(text=message.content)]))
            continue
        parts: list[types.Part] = []
        if message.content:
            parts.append(types.Part(text=message.content, thought_signature=_decode(message.signature)))
        for index, call in enumerate(message.tool_calls):
            signature = _decode(call.signature) or (_SKIP_SIGNATURE if index == 0 else None)
            parts.append(
                types.Part(
                    function_call=types.FunctionCall(id=call.id, name=call.name, args=call.arguments),
                    thought_signature=signature,
                )
            )
        if parts:
            contents.append(types.Content(role="model", parts=parts))
    flush_responses()
    return contents


def _tools(task: TaskSpec) -> list[types.Tool] | None:
    if task.web_grounded:
        return [types.Tool(google_search=types.GoogleSearch())]
    if not task.tools:
        return None
    declarations = [
        types.FunctionDeclaration(name=tool.name, description=tool.description, parameters_json_schema=tool.parameters)
        for tool in task.tools
    ]
    return [types.Tool(function_declarations=declarations)]


def _as_object(content: str) -> dict[str, Any]:
    try:
        value = json.loads(content) if content else {}
    except json.JSONDecodeError:
        return {"result": content}
    return value if isinstance(value, dict) else {"result": value}


def _map_api_error(exc: errors.APIError) -> ProviderError:
    code = getattr(exc, "code", None)
    detail = f"gemini {code} {getattr(exc, 'status', '') or ''}: {str(getattr(exc, 'message', '') or exc)[:200]}"
    if code == 429:
        return RateLimited(detail)
    if isinstance(exc, errors.ServerError) or (isinstance(code, int) and code >= 500):
        return ProviderUnavailable(detail)
    return ProviderError(detail)


def _encode(signature: bytes | None) -> str | None:
    return base64.b64encode(signature).decode("ascii") if signature else None


def _decode(signature: str | None) -> bytes | None:
    return base64.b64decode(signature) if signature else None
