"""Sub-agents: what each may use, and what comes back to the planner."""

from __future__ import annotations

import json
import pytest
from pydantic import ValidationError

from app.engine.delegation import (
    DELEGATE_TOOL,
    SUBAGENTS,
    DelegateArgs,
    delegate_tool,
    note_call,
    reply_message,
    result_content,
    start,
)
from app.tools.registry import SCOPES, AgentScopes, ToolRegistry
from app.tools.types import ToolKind, ToolScope

CALL = {"id": "c1", "gate_call_id": "4-0-c1", "name": DELEGATE_TOOL}


def test_only_the_coordinator_may_hand_work_to_a_sub_agent():
    registry = ToolRegistry([delegate_tool()])
    scopes = AgentScopes()

    assert [tool.name for tool in scopes.tools_for("orchestrator", registry)] == [DELEGATE_TOOL]
    for agent in SUBAGENTS:
        assert scopes.tools_for(agent, registry) == [], f"{agent} could delegate"
    assert ToolScope.DELEGATE not in SCOPES["research"] | SCOPES["outreach"] | SCOPES["quote"]


def test_each_sub_agent_is_granted_only_its_own_scopes():
    assert SCOPES["research"] == {ToolScope.READ}
    assert SCOPES["outreach"] == {ToolScope.READ, ToolScope.COMMUNICATION}
    assert SCOPES["quote"] == {ToolScope.READ, ToolScope.CATALOG, ToolScope.DOCUMENT}
    # Nothing outside the workspace changes without approval, whoever asks.
    assert delegate_tool().kind is ToolKind.DELEGATE


def test_a_delegated_task_has_to_say_what_to_do():
    args = DelegateArgs.model_validate({"agent": "research", "task": "Write a brief on Acme Corp"})
    assert (args.agent, args.context) == ("research", None)
    with pytest.raises(ValidationError):
        DelegateArgs.model_validate({"agent": "sales", "task": "Write a brief on Acme Corp"})
    with pytest.raises(ValidationError):
        DelegateArgs.model_validate({"agent": "research", "task": "too short"})


def test_a_sub_agent_starts_from_the_task_and_what_it_was_given():
    delegation = start(CALL, {"agent": "outreach", "task": "Email Jane the pricing", "context": "Jane is the CFO"})

    assert (delegation["agent"], delegation["id"], delegation["model_call_id"]) == ("outreach", "4-0-c1", "c1")
    [opening] = delegation["messages"]
    assert "Task: Email Jane the pricing" in opening["content"] and "Jane is the CFO" in opening["content"]
    assert delegation["steps"] == 0


def test_the_planner_gets_the_result_with_what_the_sub_agent_did():
    delegation = start(CALL, {"agent": "research", "task": "Write a brief on Acme Corp"})
    sources = [{"title": "Acme raises $20m", "url": "https://news.test/acme"}]
    note_call(delegation, "web_search", "EXECUTED", "3 pages", sources)
    note_call(delegation, "search_knowledge_base", "EXECUTED", "2 documents", sources)  # same source again
    note_call(delegation, "search_emails", "DENIED", "Gmail isn't connected", [])

    result = json.loads(result_content(delegation, "Acme raised $20m last year and renews in March."))

    assert result["ok"] and result["outcome"] == "EXECUTED"
    assert result["summary"].startswith("research agent: Acme raised $20m")
    assert [step["tool"] for step in result["data"]["steps"]] == ["web_search", "search_knowledge_base", "search_emails"]
    assert result["data"]["steps"][-1]["outcome"] == "DENIED"
    assert result["sources"] == sources  # listed once, for the rep to follow
    assert reply_message(delegation, "x").tool_call_id == "c1"


def test_a_sub_agent_that_was_stopped_reports_why():
    delegation = start(CALL, {"agent": "quote", "task": "Quote 10 Pro seats for Acme"})
    result = json.loads(result_content(delegation, "", stopped="stopped: the turn hit its step limit"))

    assert not result["ok"] and result["outcome"] == "FAILED"
    assert result["error"] == "stopped: the turn hit its step limit"


def test_what_a_sub_agent_did_stays_a_summary():
    delegation = start(CALL, {"agent": "research", "task": "Write a brief on Acme Corp"})
    for index in range(30):
        note_call(delegation, "web_search", "EXECUTED", "x" * 400, [{"title": f"p{index}", "url": f"https://news.test/{index}"}])

    assert len(delegation["log"]) == 20 and len(delegation["sources"]) == 10
    assert len(delegation["log"][0]["summary"]) == 200
