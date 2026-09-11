"""Provider-neutral LLM types. Agents build ``TaskSpec``s and read ``Completion``s; only
the providers translate to and from a vendor's wire format.

Messages are kept as plain dicts in checkpointed graph state (``to_dict``/``from_dict``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Complexity(StrEnum):
    HIGH = "high"  # planning, negotiation, quote logic → Gemini
    LOW = "low"  # summaries, classification → OpenRouter


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    # Opaque provider token that must travel back with the call on the next turn
    # (Gemini "thought signature", base64). Unknown to every other layer.
    signature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments, "signature": self.signature}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolCall:
        return cls(
            id=data["id"], name=data["name"], arguments=dict(data.get("arguments") or {}), signature=data.get("signature")
        )


def new_call_id() -> str:
    return f"call_{uuid4().hex[:24]}"


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None  # TOOL messages: which call this answers
    name: str | None = None  # TOOL messages: the tool's name
    signature: str | None = None  # provider token attached to the text part

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.tool_calls:
            data["tool_calls"] = [call.to_dict() for call in self.tool_calls]
        if self.tool_call_id:
            data["tool_call_id"] = self.tool_call_id
        if self.name:
            data["name"] = self.name
        if self.signature:
            data["signature"] = self.signature
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        return cls(
            role=Role(data["role"]),
            content=data.get("content") or "",
            tool_calls=tuple(ToolCall.from_dict(call) for call in data.get("tool_calls") or ()),
            tool_call_id=data.get("tool_call_id"),
            name=data.get("name"),
            signature=data.get("signature"),
        )


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass(frozen=True, slots=True)
class TaskSpec:
    purpose: str  # short label for traces, e.g. "plan"
    messages: tuple[Message, ...]
    system: str | None = None
    tools: tuple[ToolSpec, ...] = ()
    complexity: Complexity = Complexity.HIGH  # when unsure, the plan says default to high
    temperature: float | None = None
    max_output_tokens: int | None = None
    # Answer from a live web search (Google Search grounding). Only some providers can;
    # such a task cannot also declare tools.
    web_grounded: bool = False
    # False: the tools stay declared (the history may contain calls to them) but the model must
    # answer in text. Providers pass it on as a "no function calls" tool choice.
    allow_tool_calls: bool = True

    def __post_init__(self) -> None:
        if self.web_grounded and self.tools:
            raise ValueError("a web-grounded task cannot declare tools")


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class Source:
    """A web page a grounded answer was based on."""

    title: str
    url: str


@dataclass(frozen=True, slots=True)
class Completion:
    message: Message
    provider: str
    model: str
    usage: Usage = field(default_factory=Usage)
    finish_reason: str | None = None
    sources: tuple[Source, ...] = ()  # web-grounded tasks only


# --- streaming -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class StreamRestart:
    """The router abandoned a partially streamed answer and is failing over: consumers
    should discard the text received so far."""

    reason: str


@dataclass(frozen=True, slots=True)
class StreamDone:
    completion: Completion


StreamEvent = TextDelta | StreamRestart | StreamDone


# --- errors ----------------------------------------------------------------


class ProviderError(Exception):
    """Any failure from a model provider. The router fails over on these."""


class RateLimited(ProviderError):
    pass


class ProviderUnavailable(ProviderError):
    pass
