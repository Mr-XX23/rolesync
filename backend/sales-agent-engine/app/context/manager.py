"""The context manager (implementation-plan §6): what a model sees on each step, within budget.

The graph state keeps a session's whole conversation (the transcript the rep sees). What goes
to the model is built here:

1. **What is known about the rep:** their profile's own words for the agent and communication
   style (workspace-service), plus facts the agent saved about them (REP memory).
2. **Offloaded results:** a tool result larger than ``tool_result_max_chars`` is stored once
   (``agent.context_blob``) and the conversation keeps a preview plus a reference, which the
   ``read_offloaded_result`` tool reads back on demand.
3. **Summaries:** when the prompt would exceed ``max_prompt_tokens``, older turns are folded
   into a running summary (CONVERSATION memory, so later steps reuse it) and only the most
   recent turns go verbatim. The request being worked on is never folded.
4. **Compaction:** if the recent turns alone are still too big, their older tool results are
   replaced by references too.

Summaries come from the low-complexity model route, then the complex route; if no model
answers, a deterministic digest keeps the run going.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.context.stores import BlobStore, MemoryStore, facts_of
from app.core.clock import utcnow
from app.core.context import AgentContext
from app.core.enums import MemoryScope
from app.models.router import ModelRouter
from app.models.types import Complexity, Message, ProviderError, Role, TaskSpec, ToolSpec
from app.platform.workspace_client import RepProfile

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 3.5  # conservative for English + JSON; real tokenizers average ~4

SUMMARY_SYSTEM = """You keep the running memory of a conversation between a sales assistant and the sales rep it works for.
Update the summary with the new part of the conversation. Keep: what the rep asked for and decided; facts learned
(people and their roles, companies, numbers, prices, dates); every action taken and its outcome, with action_id
values, quote numbers, deal ids and links; anything still open. Leave out small talk and tool mechanics.
Write concise bullet points, at most 400 words. Output only the summary."""


@dataclass(frozen=True, slots=True)
class ContextBudget:
    max_prompt_tokens: int  # system + tool definitions + conversation
    keep_recent_turns: int = 2  # turns kept word for word (the current one always is)
    tool_result_max_chars: int = 24_000  # larger results are stored and referenced
    preview_chars: int = 2_000
    summary_max_chars: int = 6_000
    rep_context_chars: int = 3_000
    summary_timeout_seconds: float = 45.0


class RepProfiles(Protocol):
    async def get(self, user_id: UUID) -> RepProfile | None: ...


@dataclass(frozen=True, slots=True)
class PreparedContext:
    system: str
    messages: tuple[Message, ...]
    estimated_tokens: int
    folded_through: int  # messages before this index are represented by the summary
    compacted_results: int  # tool results shown only as references in this prompt


def estimate_tokens(chars: int) -> int:
    return int(chars / CHARS_PER_TOKEN) + 1


def message_chars(message: Message) -> int:
    size = len(message.content) + 16
    for call in message.tool_calls:
        size += len(call.name) + len(json.dumps(call.arguments, default=str)) + 32
    return size


def tool_chars(tools: Sequence[ToolSpec]) -> int:
    return sum(len(tool.name) + len(tool.description) + len(json.dumps(tool.parameters)) for tool in tools)


def estimate_task_tokens(task: TaskSpec) -> int:
    """The same estimate the manager budgets with, for any task a model receives."""
    chars = len(task.system or "") + tool_chars(task.tools) + sum(message_chars(message) for message in task.messages)
    return estimate_tokens(chars)


class ContextManager:
    def __init__(
        self,
        *,
        memory: MemoryStore,
        blobs: BlobStore,
        router: ModelRouter,
        budget: ContextBudget,
        profiles: RepProfiles | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._memory = memory
        self._blobs = blobs
        self._router = router
        self._budget = budget
        self._profiles = profiles
        self._clock = clock

    # ------------------------------------------------------------------ tool results
    async def keep_result(self, ctx: AgentContext, *, call_id: str, tool: str, content: str) -> str:
        """The tool reply to keep in the conversation: the result itself, or for a result that is
        too large, a reference to the stored copy with a preview."""
        if len(content) <= self._budget.tool_result_max_chars:
            return content
        try:
            ref = await self._blobs.put(
                tenant_id=ctx.tenant_id, session_id=ctx.session_id, call_id=call_id, tool=tool, content=content
            )
        except Exception:
            logger.exception("could not store a large %s result; keeping a truncated copy", tool)
            return _compact(content, None, self._budget.preview_chars)
        return _compact(content, ref, self._budget.preview_chars)

    # ------------------------------------------------------------------ prompt
    async def prepare(
        self,
        ctx: AgentContext,
        *,
        history: Sequence[dict[str, Any]],
        system: str,
        tools: Sequence[ToolSpec],
        on_fold: Callable[[], Any] | None = None,
    ) -> PreparedContext:
        messages = [Message.from_dict(item) for item in history]
        rep = await self._rep_block(ctx)
        base_system = f"{system}\n\n{rep}" if rep else system
        fixed_chars = tool_chars(tools)
        budget = self._budget.max_prompt_tokens

        conversation = await self._memory.latest(tenant_id=ctx.tenant_id, scope=MemoryScope.CONVERSATION, key=str(ctx.session_id))
        summary = str(conversation.content.get("summary") or "") if conversation else ""
        through = min(int(conversation.content.get("through") or 0), len(messages)) if conversation else 0

        def assemble(summary_text: str, start: int, visible: list[Message] | None = None) -> tuple[str, list[Message], int]:
            shown = visible if visible is not None else messages[start:]
            system_text = base_system + (f"\n\nEarlier in this conversation (summary):\n{summary_text}" if summary_text else "")
            chars = len(system_text) + fixed_chars + sum(message_chars(message) for message in shown)
            return system_text, shown, estimate_tokens(chars)

        system_text, visible, estimate = assemble(summary, through)
        if estimate > budget:
            turn_starts = [index for index, message in enumerate(messages) if message.role is Role.USER]
            keep = max(1, self._budget.keep_recent_turns)
            while True:
                boundary = turn_starts[-keep] if len(turn_starts) >= keep else (turn_starts[0] if turn_starts else 0)
                if boundary > through:
                    if on_fold is not None:
                        await on_fold()
                    summary = await self._fold(ctx, summary, messages[through:boundary], through=boundary)
                    through = boundary
                system_text, visible, estimate = assemble(summary, through)
                if estimate <= budget or keep == 1:
                    break
                keep -= 1

        compacted = 0
        if estimate > budget:
            visible = list(visible)
            result_positions = [index for index, message in enumerate(visible) if message.role is Role.TOOL]
            for index in result_positions[:-2]:  # the newest results stay whole
                message = visible[index]
                if _is_compact(message.content) or len(message.content) <= self._budget.preview_chars:
                    continue
                ref = await self._blobs.put(
                    tenant_id=ctx.tenant_id,
                    session_id=ctx.session_id,
                    call_id=f"msg-{through + index}",
                    tool=message.name or "tool",
                    content=message.content,
                )
                visible[index] = replace(message, content=_compact(message.content, ref, 600))
                compacted += 1
                system_text, visible, estimate = assemble(summary, through, visible)
                if estimate <= budget:
                    break
        if estimate > budget:
            # Last resort: clip what remains. The per-turn token limit still guards the run.
            visible = [
                replace(message, content=message.content[:800]) if message.role is Role.TOOL else message for message in visible
            ]
            system_text, visible, estimate = assemble(summary, through, visible)
        return PreparedContext(
            system=system_text,
            messages=tuple(visible),
            estimated_tokens=estimate,
            folded_through=through,
            compacted_results=compacted,
        )

    # ------------------------------------------------------------------ summaries
    async def _fold(self, ctx: AgentContext, summary: str, messages: Sequence[Message], *, through: int) -> str:
        """Fold ``messages`` into the running summary, a few turns at a time, and store it."""
        method = "model"
        for chunk in _chunks_by_turn(messages, max_chars=30_000):
            transcript = render_transcript(chunk)
            text = await self._summarize(summary, transcript)
            if text is None:
                method = "digest"
                text = digest(summary, chunk, limit=self._budget.summary_max_chars)
            summary = text[: self._budget.summary_max_chars]

        stored_summary = summary

        def store(content: dict[str, Any]) -> dict[str, Any] | None:
            if int(content.get("through") or 0) >= through:
                return None  # another step already folded at least this far
            return {"summary": stored_summary, "through": through, "method": method, "updated_at": self._clock().isoformat()}

        record = await self._memory.update(
            tenant_id=ctx.tenant_id, scope=MemoryScope.CONVERSATION, key=str(ctx.session_id), mutate=store, written_by=ctx.user_id
        )
        if record is not None and int(record.content.get("through") or 0) > through:
            return str(record.content.get("summary") or summary)
        return summary

    async def _summarize(self, summary: str, transcript: str) -> str | None:
        prompt = f"Summary so far:\n{summary or '(nothing yet)'}\n\nNew part of the conversation:\n{transcript}"
        for complexity in (Complexity.LOW, Complexity.HIGH):
            task = TaskSpec(
                purpose="summarize-conversation",
                system=SUMMARY_SYSTEM,
                messages=(Message(role=Role.USER, content=prompt),),
                complexity=complexity,
                max_output_tokens=1_500,
            )
            if not self._router.can_serve(task):
                continue
            try:
                async with asyncio.timeout(self._budget.summary_timeout_seconds):
                    completion = await self._router.complete(task)
            except (ProviderError, TimeoutError) as exc:
                logger.warning("conversation summary on the %s route failed: %s", complexity.value, exc)
                continue
            text = completion.message.content.strip()
            if text:
                return text
        return None

    # ------------------------------------------------------------------ rep
    async def rep_context(self, ctx: AgentContext) -> str:
        """What is known about the rep, for a sub-agent's prompt (the planner gets it from ``prepare``)."""
        return await self._rep_block(ctx)

    async def _rep_block(self, ctx: AgentContext) -> str:
        profile: RepProfile | None = None
        if self._profiles is not None:
            try:
                profile = await self._profiles.get(ctx.user_id)
            except Exception:
                logger.warning("could not load the rep's profile", exc_info=True)
        record = await self._memory.latest(tenant_id=ctx.tenant_id, scope=MemoryScope.REP, key=str(ctx.user_id))
        facts = facts_of(record.content if record else None)

        lines: list[str] = []
        if profile is not None:
            who = ", ".join(part for part in (profile.first_name, profile.job_title) if part)
            if who:
                lines.append(f"- Rep: {who}")
            if profile.communication_style:
                lines.append(f"- Preferred communication style: {profile.communication_style}")
            if profile.persona_context:
                lines.append(f"- In their own words: {_clip(profile.persona_context, 1_500)}")
        if facts:
            lines.append("- What you have learned about them (id in brackets, for forget):")
            budget = self._budget.rep_context_chars
            for fact in reversed(facts):  # newest first
                line = f"  - {fact.get('text')} [{fact.get('id')}]"
                budget -= len(line)
                if budget < 0:
                    break
                lines.append(line)
        if not lines:
            return ""
        return "About the rep you work for (follow their preferences unless they say otherwise):\n" + "\n".join(lines)


# ----------------------------------------------------------------------------- helpers


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _is_compact(content: str) -> bool:
    return '"offloaded"' in content[:400] or '"truncated": true' in content[:400]


def _compact(content: str, ref: UUID | None, preview_chars: int) -> str:
    """A tool reply that points at the stored full result instead of carrying it."""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        payload = {"result": content}
    if not isinstance(payload, dict):
        payload = {"result": payload}
    compact = {key: payload[key] for key in ("ok", "outcome", "summary", "error", "sources", "action_id", "undoable") if key in payload}
    body = payload.get("data", payload.get("result"))
    preview = json.dumps(body, ensure_ascii=False, default=str) if not isinstance(body, str) else body
    compact["data_preview"] = _clip(preview, preview_chars)
    if ref is not None:
        compact["offloaded"] = {
            "ref": str(ref),
            "chars": len(content),
            "how_to_read": "This result was too long to keep here. Call read_offloaded_result with this ref to read it.",
        }
    else:
        compact["truncated"] = True
    return json.dumps(compact, ensure_ascii=False)


def _chunks_by_turn(messages: Sequence[Message], *, max_chars: int) -> list[list[Message]]:
    """Whole turns (a rep message and everything after it), grouped up to ``max_chars``."""
    turns: list[list[Message]] = []
    for message in messages:
        if message.role is Role.USER or not turns:
            turns.append([])
        turns[-1].append(message)
    chunks: list[list[Message]] = []
    size = 0
    for turn in turns:
        turn_size = len(render_transcript(turn))
        if chunks and size + turn_size > max_chars:
            chunks.append([])
            size = 0
        if not chunks:
            chunks.append([])
        chunks[-1].extend(turn)
        size += turn_size
    return chunks


def render_transcript(messages: Sequence[Message]) -> str:
    """A compact, model-readable rendering of conversation messages (for summaries)."""
    lines: list[str] = []
    for message in messages:
        if message.role is Role.USER:
            lines.append(f"Rep: {_clip(message.content, 1_500)}")
        elif message.role is Role.ASSISTANT:
            if message.content:
                lines.append(f"Assistant: {_clip(message.content, 1_500)}")
            for call in message.tool_calls:
                lines.append(f"  -> {call.name}({_clip(json.dumps(call.arguments, ensure_ascii=False, default=str), 300)})")
        else:
            try:
                result = json.loads(message.content)
            except json.JSONDecodeError:
                result = {"summary": message.content}
            if not isinstance(result, dict):
                result = {"summary": str(result)}
            parts = [str(result.get("outcome") or "")]
            detail = result.get("summary") or result.get("error")
            if detail:
                parts.append(str(detail))
            if result.get("action_id"):
                parts.append(f"action_id {result['action_id']}")
            data = result.get("data", result.get("data_preview"))
            if data:
                parts.append(_clip(json.dumps(data, ensure_ascii=False, default=str) if not isinstance(data, str) else data, 400))
            lines.append(f"  <- {message.name}: {_clip(' | '.join(part for part in parts if part), 700)}")
    return "\n".join(lines)


def digest(summary: str, messages: Sequence[Message], *, limit: int) -> str:
    """A summary without a model: the rep's requests, the actions taken, and the answers."""
    lines = [summary] if summary else []
    for message in messages:
        if message.role is Role.USER:
            lines.append(f"- Rep asked: {_clip(message.content, 240)}")
        elif message.role is Role.ASSISTANT and message.content and not message.tool_calls:
            lines.append(f"  Answered: {_clip(message.content, 240)}")
        elif message.role is Role.TOOL:
            try:
                result = json.loads(message.content)
            except json.JSONDecodeError:
                result = {}
            if isinstance(result, dict):
                detail = result.get("summary") or result.get("error") or ""
                action = f" (action_id {result['action_id']})" if result.get("action_id") else ""
                lines.append(f"  Did {message.name}: {result.get('outcome', '')} {_clip(str(detail), 180)}{action}".rstrip())
    text = "\n".join(line for line in lines if line)
    if len(text) <= limit:
        return text
    return "…" + text[-(limit - 1):]  # keep the most recent part
