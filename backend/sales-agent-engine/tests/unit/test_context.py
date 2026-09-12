"""Context manager (budgeted prompts, summaries, offloaded results) and memory primitives."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.context.manager import ContextBudget, ContextManager, digest, estimate_task_tokens, render_transcript
from app.context.stores import MemoryRecord, account_key, add_fact, facts_of, normalize_fact, remove_fact
from app.core.context import AgentContext, RunMode
from app.core.enums import MemoryScope
from app.models.types import Completion, Message, ProviderUnavailable, Role, TaskSpec, ToolCall, ToolSpec
from app.platform.workspace_client import RepProfile

NOW = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
CTX = AgentContext(tenant_id=uuid4(), user_id=uuid4(), session_id=uuid4(), mode=RunMode.INTERACTIVE, turn=5)


class FakeMemory:
    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, str, str], list[MemoryRecord]] = {}

    async def latest(self, *, tenant_id, scope, key):
        versions = self.rows.get((tenant_id, str(scope), key))
        return versions[-1] if versions else None

    async def list_latest(self, *, tenant_id, scope, limit=200):
        return [versions[-1] for (tenant, kind, _), versions in self.rows.items() if tenant == tenant_id and kind == str(scope)]

    async def update(self, *, tenant_id, scope, key, mutate, written_by):
        current = await self.latest(tenant_id=tenant_id, scope=scope, key=key)
        changed = mutate(copy.deepcopy(current.content) if current else {})
        if changed is None:
            return current
        record = MemoryRecord(MemoryScope(scope), key, (current.version if current else 0) + 1, changed, NOW, written_by)
        self.rows.setdefault((tenant_id, str(scope), key), []).append(record)
        return record


class FakeBlobs:
    def __init__(self) -> None:
        self.stored: dict[UUID, tuple[str, str]] = {}
        self.by_call: dict[str, UUID] = {}

    async def put(self, *, tenant_id, session_id, call_id, tool, content):
        if call_id not in self.by_call:
            ref = uuid4()
            self.by_call[call_id] = ref
            self.stored[ref] = (tool, content)
        return self.by_call[call_id]


class FakeRouter:
    def __init__(self, *, answer: str | None = None) -> None:
        self.answer = answer
        self.tasks: list[TaskSpec] = []

    def can_serve(self, task: TaskSpec) -> bool:
        return True

    async def complete(self, task: TaskSpec) -> Completion:
        self.tasks.append(task)
        if self.answer is None:
            raise ProviderUnavailable("no model today")
        return Completion(message=Message(role=Role.ASSISTANT, content=self.answer), provider="fake", model="fake")


class Profiles:
    async def get(self, user_id: UUID) -> RepProfile | None:
        return RepProfile(first_name="Rohan", job_title="Account Executive", communication_style="Concise",
                          persona_context="I sell to fintech CFOs. Keep emails under 120 words.")


def _manager(memory=None, blobs=None, router=None, *, budget: int = 4_000, **overrides: Any) -> ContextManager:
    return ContextManager(
        memory=memory or FakeMemory(),
        blobs=blobs or FakeBlobs(),
        router=router or FakeRouter(),
        budget=ContextBudget(max_prompt_tokens=budget, **overrides),
        clock=lambda: NOW,
    )


def _turn(number: int, *, result_chars: int = 3_000) -> list[dict[str, Any]]:
    """One rep request answered after a tool call with a sizeable result."""
    call = ToolCall(id=f"c{number}", name="search_catalog", arguments={"query": f"topic {number}"})
    result = {"ok": True, "outcome": "EXECUTED", "summary": f"found things for request {number}", "data": {"text": "x" * result_chars}}
    return [
        Message(role=Role.USER, content=f"Request {number}: tell me about topic {number}").to_dict(),
        Message(role=Role.ASSISTANT, content="Looking.", tool_calls=(call,)).to_dict(),
        Message(role=Role.TOOL, content=json.dumps(result), tool_call_id=call.id, name=call.name).to_dict(),
        Message(role=Role.ASSISTANT, content=f"Answer {number}: " + "details " * 60).to_dict(),
    ]


TOOLS = (ToolSpec("search_catalog", "Search the catalog", {"type": "object", "properties": {"query": {"type": "string"}}}),)


def test_account_keys_ignore_case_punctuation_and_legal_suffixes():
    assert account_key("Acme Corp.") == account_key("ACME, Inc") == account_key("acme") == "acme"
    assert account_key("Globex Corporation Ltd") == "globex"
    assert account_key("Zürich Versicherung AG") == "zurich-versicherung"
    assert account_key("Inc") == "inc"  # a name that is only a suffix stays a name
    assert account_key("深圳科技") == "深圳科技"
    assert account_key("深圳 / 科技") == "深圳-科技"
    for name in ("Acme Corp.", "Zürich Versicherung AG", "深圳 / 科技"):
        assert account_key(account_key(name)) == account_key(name)  # a key resolves to itself
    with pytest.raises(ValueError):
        account_key("   ")
    with pytest.raises(ValueError):
        account_key(" / ")


def test_facts_are_deduplicated_capped_and_removable():
    content: dict[str, Any] = {}
    content, first = add_fact(content, "Prefers  short emails.", saved_by=CTX.user_id, session_id=CTX.session_id, now=NOW, limit=3)
    again, same = add_fact(content, "prefers short emails", saved_by=uuid4(), session_id=None, now=NOW, limit=3)
    assert again is None and same["id"] == first["id"]  # already known
    for text in ("Signs off as Rohan", "Likes 30 minute calls", "Travels on Mondays"):
        content, _ = add_fact(content, text, saved_by=None, session_id=None, now=NOW, limit=3)
    assert [fact["text"] for fact in facts_of(content)] == ["Signs off as Rohan", "Likes 30 minute calls", "Travels on Mondays"]
    kept = remove_fact(content, facts_of(content)[0]["id"])
    assert kept is not None and len(facts_of(kept)) == 2
    assert remove_fact(content, "f_000000000000") is None
    assert normalize_fact(" Budget is $50k! ") == "budget is $50k"


async def test_small_results_stay_and_large_ones_are_stored_with_a_preview():
    blobs = FakeBlobs()
    manager = _manager(blobs=blobs, tool_result_max_chars=1_000, preview_chars=200)
    small = json.dumps({"ok": True, "outcome": "EXECUTED", "summary": "3 items"})
    assert await manager.keep_result(CTX, call_id="1-0-a", tool="search_catalog", content=small) == small

    large = json.dumps({"ok": True, "outcome": "EXECUTED", "summary": "the whole document", "action_id": "x", "data": {"text": "word " * 2_000}})
    kept = json.loads(await manager.keep_result(CTX, call_id="1-1-b", tool="read_knowledge_document", content=large))
    assert kept["summary"] == "the whole document" and kept["action_id"] == "x"
    assert len(kept["data_preview"]) <= 200
    ref = UUID(kept["offloaded"]["ref"])
    assert blobs.stored[ref] == ("read_knowledge_document", large) and kept["offloaded"]["chars"] == len(large)
    # The same call again (a replayed step) references the same stored copy.
    assert json.loads(await manager.keep_result(CTX, call_id="1-1-b", tool="read_knowledge_document", content=large))["offloaded"]["ref"] == str(ref)


async def test_a_short_conversation_goes_to_the_model_unchanged():
    history = _turn(1)
    prepared = await _manager(budget=50_000).prepare(CTX, history=history, system="SYSTEM", tools=TOOLS)
    assert [message.to_dict() for message in prepared.messages] == history
    assert prepared.system == "SYSTEM" and prepared.folded_through == 0


async def test_older_turns_are_summarized_to_fit_the_budget_and_the_summary_is_reused():
    memory, router = FakeMemory(), FakeRouter(answer="- Rep asked about topics 1-4; answers given.")
    manager = _manager(memory, router=router, budget=2_500)
    history = [message for number in range(1, 7) for message in _turn(number)]

    prepared = await manager.prepare(CTX, history=history, system="SYSTEM", tools=TOOLS)

    assert prepared.estimated_tokens <= 2_500
    assert prepared.messages[0].role is Role.USER  # the window starts at a turn
    assert prepared.messages[-1].content.startswith("Answer 6")  # the latest turn is intact
    assert "Earlier in this conversation (summary):\n- Rep asked about topics 1-4" in prepared.system
    [stored] = memory.rows[(CTX.tenant_id, "CONVERSATION", str(CTX.session_id))]
    assert stored.content["through"] == prepared.folded_through > 0 and stored.content["method"] == "model"
    summarize = router.tasks[0]
    assert summarize.purpose == "summarize-conversation" and "Request 1: tell me about topic 1" in summarize.messages[0].content
    assert estimate_task_tokens(TaskSpec(purpose="plan", system=prepared.system, messages=prepared.messages, tools=TOOLS)) <= 2_500

    calls = len(router.tasks)
    again = await manager.prepare(CTX, history=history, system="SYSTEM", tools=TOOLS)
    assert len(router.tasks) == calls and again.folded_through == prepared.folded_through  # nothing new to fold


async def test_without_a_model_the_summary_is_a_digest_and_the_run_goes_on():
    memory = FakeMemory()
    manager = _manager(memory, router=FakeRouter(answer=None), budget=2_500)
    history = [message for number in range(1, 7) for message in _turn(number)]

    prepared = await manager.prepare(CTX, history=history, system="SYSTEM", tools=TOOLS)

    assert prepared.estimated_tokens <= 2_500
    assert "- Rep asked: Request 1: tell me about topic 1" in prepared.system
    assert "Did search_catalog: EXECUTED found things for request 1" in prepared.system
    stored = memory.rows[(CTX.tenant_id, "CONVERSATION", str(CTX.session_id))][-1]
    assert stored.content["method"] == "digest" and stored.content["through"] == prepared.folded_through


async def test_a_huge_current_request_keeps_its_newest_results_and_references_the_rest():
    blobs = FakeBlobs()
    manager = _manager(blobs=blobs, budget=4_500, keep_recent_turns=1)
    turn = [Message(role=Role.USER, content="Research everything").to_dict()]
    for index in range(6):
        call = ToolCall(id=f"r{index}", name="web_search", arguments={"query": f"q{index}"})
        turn.append(Message(role=Role.ASSISTANT, content="", tool_calls=(call,)).to_dict())
        payload = {"ok": True, "outcome": "EXECUTED", "summary": f"page {index}", "data": {"text": "y" * 4_000}}
        turn.append(Message(role=Role.TOOL, content=json.dumps(payload), tool_call_id=call.id, name="web_search").to_dict())

    prepared = await manager.prepare(CTX, history=turn, system="SYSTEM", tools=TOOLS)

    assert prepared.estimated_tokens <= 4_500
    results = [message for message in prepared.messages if message.role is Role.TOOL]
    assert len(results) == 6 and prepared.compacted_results >= 1
    assert '"offloaded"' in results[0].content and blobs.stored
    assert results[-1].content.endswith('"}}')  # the newest result is whole


async def test_what_is_known_about_the_rep_goes_into_the_system_prompt():
    memory = FakeMemory()
    await memory.update(
        tenant_id=CTX.tenant_id, scope=MemoryScope.REP, key=str(CTX.user_id), written_by=CTX.user_id,
        mutate=lambda content: add_fact(content, "Signs emails as 'Best, Rohan'", saved_by=CTX.user_id, session_id=None, now=NOW, limit=10)[0],
    )
    manager = ContextManager(memory=memory, blobs=FakeBlobs(), router=FakeRouter(), budget=ContextBudget(max_prompt_tokens=50_000), profiles=Profiles())

    prepared = await manager.prepare(CTX, history=_turn(1), system="SYSTEM", tools=TOOLS)

    assert "About the rep you work for" in prepared.system
    assert "Rep: Rohan, Account Executive" in prepared.system and "Preferred communication style: Concise" in prepared.system
    assert "In their own words: I sell to fintech CFOs." in prepared.system
    assert "Signs emails as 'Best, Rohan' [f_" in prepared.system


def test_transcripts_and_digests_keep_what_matters():
    messages = [Message.from_dict(item) for item in _turn(1, result_chars=50)]
    text = render_transcript(messages)
    assert "Rep: Request 1" in text and "-> search_catalog(" in text and "<- search_catalog: EXECUTED | found things" in text
    long = digest("", messages * 50, limit=500)
    assert len(long) <= 500 and long.startswith("…")
