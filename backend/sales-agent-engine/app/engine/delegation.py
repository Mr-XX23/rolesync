"""Sub-agents the orchestrator hands work to (implementation-plan §10 Phase 5).

The orchestrator stays the sole coordinator: it calls ``delegate``, the sub-agent works in its
own short conversation, and only its **result** comes back to the planner — never its steps.
Each sub-agent has its own tools, granted by ``registry.SCOPES`` and enforced at the gate, so a
research sub-agent asking to send an email is refused there, not by a prompt.

A sub-agent's conversation lives in the orchestrator's graph state (``delegations``), because a
write inside a sub-agent pauses the whole run for approval: the state has to survive the pause
and resume exactly where it stopped, the same way the orchestrator's own steps do.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field

from app.models.types import Message, Role
from app.tools.registry import ToolDefinition
from app.tools.types import ToolCategory, ToolInput, ToolInvocation, ToolKind, ToolOutput, ToolScope

DELEGATE_TOOL = "delegate"

_COMMON = """
You are working on one task for a sales rep, handed to you by their assistant. You cannot see the
rep's conversation and cannot ask them anything: work from the task and what your tools tell you.
When you are done, answer in plain words with your result — that answer is all the assistant gets
back, so it has to stand on its own. If something essential is missing, stop and say what it is."""

RESEARCH_PROMPT = """You are the research sub-agent. You gather facts. You never contact anyone and
change nothing.

- Use every source the task spans: the web, the workspace knowledge base, the rep's email, calendar,
  Slack and Notion, the catalog, deals, and what the assistant remembers about the customer. Ask for
  independent reads together in one step.
- Base everything on tool results. Cite web facts with their URLs, and name the documents, emails or
  messages you used. If something isn't there, say so instead of guessing.
- When a source finds nothing, try one differently worded search there at most, then move on. Don't
  retry a source that was DENIED (an app the rep hasn't connected).

Answer with the brief itself: what matters for this task, grouped, short, with citations.
""" + _COMMON

OUTREACH_PROMPT = """You are the outreach sub-agent. You write and send the rep's messages: email,
calendar invites, Slack messages and Notion pages.

- Write in the rep's voice: clear, short, professional, friendly. Check details first with the read
  tools (past emails, the calendar, what the assistant remembers) when the task leaves them open.
- Every send pauses for the rep's approval and the card names you. Call the tool directly with final
  content; never ask for permission in words. One action at a time.
- REJECTED means the rep wants something different: stop and report it, don't retry it unchanged.
  FAILED or DENIED: report it. UNKNOWN may already have happened: never retry it.

Answer with what you sent, or tried to send, and what the rep decided.
""" + _COMMON

QUOTE_PROMPT = """You are the quote sub-agent. You price work from the catalog and produce the quote.

- Prices, discount limits and stock come only from the catalog tools. Never invent a price, and keep
  every line's discount inside that item's limit.
- Search the catalog (and check stock when the task cares about it), then call create_quote with the
  exact SKUs, quantities and discounts. Pass deal_id when the task names a deal, so the quote is
  attached to it.
- create_quote pauses for the rep's approval and the card names you. If it is REJECTED, report that
  rather than quietly trying another price.

Answer with the quote's number, total and link, or with what stopped you.
""" + _COMMON


@dataclass(frozen=True, slots=True)
class SubAgent:
    name: str
    title: str  # for the rep: "research agent"
    purpose: str  # for the orchestrator, inside the delegate tool's description
    prompt: str
    max_steps: int = 6


SUBAGENTS: Mapping[str, SubAgent] = {
    "research": SubAgent(
        name="research",
        title="research agent",
        purpose="reads every source (web, knowledge base, email, calendar, Slack, Notion, catalog, deals, memory) and writes a cited brief",
        prompt=RESEARCH_PROMPT,
    ),
    "outreach": SubAgent(
        name="outreach",
        title="outreach agent",
        purpose="writes and sends email, calendar invites, Slack messages and Notion pages (each pauses for the rep's approval)",
        prompt=OUTREACH_PROMPT,
    ),
    "quote": SubAgent(
        name="quote",
        title="quote agent",
        purpose="prices items from the catalog and produces the quote document (pauses for the rep's approval)",
        prompt=QUOTE_PROMPT,
    ),
}

AgentName = Literal["research", "outreach", "quote"]


class DelegateArgs(ToolInput):
    agent: AgentName = Field(description="Which sub-agent should do the work")
    task: str = Field(
        min_length=10,
        max_length=2000,
        description="What to accomplish, in full: names, addresses, dates, amounts, constraints. The sub-agent cannot see this conversation.",
    )
    context: str | None = Field(
        default=None,
        max_length=6000,
        description="Facts already gathered that it needs (for example a research brief to write the email from)",
    )


def delegate_tool() -> ToolDefinition:
    """The coordinator's only way to start a sub-agent. Scoped so a sub-agent can't delegate."""

    async def handler(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, DelegateArgs)
        agent = SUBAGENTS[args.agent]
        return ToolOutput(
            data={"agent": agent.name, "task": args.task},
            summary=f"handed to the {agent.title}",
        )

    roster = "\n".join(f"- {agent.name}: {agent.purpose}" for agent in SUBAGENTS.values())
    return ToolDefinition(
        name=DELEGATE_TOOL,
        description=(
            "Hand a piece of work to a sub-agent and get its result back. Use it when part of the request needs "
            "several steps in one area, rather than doing those steps yourself:\n"
            f"{roster}\n"
            "The sub-agent cannot see this conversation, so put everything it needs in task and context. "
            "You get only its result, not its steps."
        ),
        kind=ToolKind.DELEGATE,
        scope=ToolScope.DELEGATE,
        category=ToolCategory.ACTION,
        input_model=DelegateArgs,
        handler=handler,
    )


# ----------------------------------------------------------------------------- state


def start(call: dict[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
    """The state of a sub-agent that is about to take its first step."""
    agent = SUBAGENTS[str(args["agent"])]
    task = str(args["task"])
    context = str(args.get("context") or "").strip()
    opening = f"Task: {task}"
    if context:
        opening += f"\n\nWhat is already known:\n{context}"
    return {
        "id": call["gate_call_id"],
        "agent": agent.name,
        "model_call_id": call["id"],
        "task": task,
        "messages": [Message(role=Role.USER, content=opening).to_dict()],
        "steps": 0,
        "log": [],  # {"tool", "outcome", "summary"} per call, for the rep and the planner
        "sources": [],
    }


def note_call(delegation: dict[str, Any], tool: str, outcome: str, summary: str | None, sources: list[dict[str, str]]) -> None:
    """Record what the sub-agent did, so its result can show its working."""
    delegation["log"] = [*(delegation.get("log") or []), {"tool": tool, "outcome": outcome, "summary": (summary or "")[:200]}][-20:]
    known = {(source.get("url") or "") for source in delegation.get("sources") or []}
    extra = [source for source in sources if source.get("url") and source["url"] not in known]
    delegation["sources"] = [*(delegation.get("sources") or []), *extra][:10]


def result_content(delegation: dict[str, Any], answer: str, *, stopped: str | None = None) -> str:
    """What the planner sees: the sub-agent's answer, what it did, and where the facts came from."""
    agent = SUBAGENTS[delegation["agent"]]
    payload: dict[str, Any] = {
        "ok": stopped is None,
        "outcome": "EXECUTED" if stopped is None else "FAILED",
        "summary": f"{agent.title}: {(answer or stopped or '').strip()[:4000]}",
        "data": {
            "agent": agent.name,
            "answer": answer.strip(),
            "steps": delegation.get("log") or [],
        },
    }
    if stopped is not None:
        payload["error"] = stopped
    if delegation.get("sources"):
        payload["sources"] = delegation["sources"]
    return json.dumps(payload)


def reply_message(delegation: dict[str, Any], content: str) -> Message:
    """The tool reply that answers the orchestrator's ``delegate`` call."""
    return Message(role=Role.TOOL, content=content, tool_call_id=delegation["model_call_id"], name=DELEGATE_TOOL)
