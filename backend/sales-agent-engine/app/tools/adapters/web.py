"""Web research tools: ``web_search`` and ``research_prospect``.

Web search uses both backends at once (a user decision): Tavily for ranked pages with
extracts, and Google Search grounding (through the model router) for a written answer
with its sources. Whichever is configured and answering is used.

``research_prospect`` gathers public information about a company and has the cheap model
route (``Complexity.LOW`` → OpenRouter) condense it into a pre-call brief, so the planner
reads a page of findings instead of every search result. It only reads the public web;
the rep's own history (emails, knowledge base) stays behind its own gated tools.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date

from pydantic import Field

from app.models.router import ModelRouter
from app.models.types import Complexity, Message, ProviderError, Role, TaskSpec
from app.platform.web_search import TavilySearch, WebPage, WebSearchError
from app.tools.adapters.common import clip, plural
from app.tools.registry import ToolDefinition
from app.tools.types import SourceLink, ToolCategory, ToolFailed, ToolInput, ToolInvocation, ToolKind, ToolOutput, ToolScope

logger = logging.getLogger(__name__)

_GROUNDED_SYSTEM = (
    "Answer from current web search results only. Be factual and concise (at most 150 words). "
    "If the results don't answer the question, say so."
)
_BRIEF_SYSTEM = (
    "You prepare short, factual pre-call briefs for a B2B sales rep. Use only the numbered sources you are given. "
    "Cite them as [n]. Write 'not found' when the sources don't cover something; never invent names, numbers or dates."
)


class WebSearchArgs(ToolInput):
    query: str = Field(min_length=2, max_length=300)
    max_results: int = Field(default=5, ge=1, le=10)
    recent_days: int | None = Field(default=None, ge=1, le=365, description="Only news from the last N days")


class ResearchProspectArgs(ToolInput):
    company: str = Field(min_length=2, max_length=150)
    website: str | None = Field(default=None, max_length=200)
    person: str | None = Field(default=None, max_length=150, description="A contact there, e.g. 'Jane Doe, VP Sales'")
    focus: str | None = Field(default=None, max_length=300, description="What the rep wants to learn or sell")


@dataclass
class Findings:
    answer: str | None = None
    answer_sources: list[SourceLink] = field(default_factory=list)
    pages: list[WebPage] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def links(self, limit: int) -> tuple[SourceLink, ...]:
        seen: dict[str, SourceLink] = {}
        for link in [*self.answer_sources, *(SourceLink(title=page.title, url=page.url) for page in self.pages)]:
            seen.setdefault(link.url, link)
        return tuple(seen.values())[:limit]


class WebResearch:
    def __init__(self, *, router: ModelRouter, tavily: TavilySearch | None, grounding: bool) -> None:
        if tavily is None and not grounding:
            raise ValueError("web research needs Tavily or Google Search grounding")
        self._router = router
        self._tavily = tavily
        self._grounding = grounding

    @property
    def returns_pages(self) -> bool:
        """Whether ranked pages (Tavily) are available, not just grounded answers."""
        return self._tavily is not None

    async def search(self, query: str, *, max_results: int, news_days: int | None = None, grounded: bool = True) -> Findings:
        """Pages from Tavily and, when ``grounded`` (or Tavily isn't configured), a Google-grounded answer."""
        findings = Findings()
        jobs = []
        if self._grounding and (grounded or self._tavily is None):
            jobs.append(self._grounded(query, findings))
        if self._tavily is not None:
            jobs.append(self._pages(query, max_results, news_days, findings))
        await asyncio.gather(*jobs)
        if findings.answer is None and not findings.pages and findings.problems:
            raise ToolFailed("web search failed: " + "; ".join(findings.problems))
        return findings

    async def _grounded(self, query: str, findings: Findings) -> None:
        task = TaskSpec(
            purpose="web_search", system=_GROUNDED_SYSTEM, messages=(Message(role=Role.USER, content=query),), web_grounded=True
        )
        try:
            completion = await self._router.complete(task)
        except ProviderError as exc:
            logger.warning("grounded web search failed for %r: %s", query, exc)
            findings.problems.append(f"Google Search: {exc}")
            return
        findings.answer = completion.message.content.strip() or None
        findings.answer_sources = [SourceLink(title=source.title, url=source.url) for source in completion.sources]
        if findings.answer is None:
            findings.problems.append("Google Search returned no answer")

    async def _pages(self, query: str, max_results: int, news_days: int | None, findings: Findings) -> None:
        assert self._tavily is not None
        try:
            findings.pages = await self._tavily.search(query, max_results=max_results, news_days=news_days)
        except WebSearchError as exc:
            logger.warning("Tavily search failed for %r: %s", query, exc)
            findings.problems.append(str(exc))


def web_tools(research: WebResearch, router: ModelRouter) -> list[ToolDefinition]:
    async def web_search(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, WebSearchArgs)
        findings = await research.search(args.query, max_results=args.max_results, news_days=args.recent_days)
        results = [
            {"title": page.title, "url": page.url, "extract": clip(page.snippet, 500), "published": page.published}
            for page in findings.pages
        ]
        summary = f"{plural(len(results), 'web result')} for '{args.query}'"
        if findings.answer:
            summary += " and an answer from Google Search"
        return ToolOutput(
            data={"answer": findings.answer, "results": results}, summary=summary, sources=findings.links(limit=8)
        )

    async def research_prospect(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, ResearchProspectArgs)
        name = args.company + (f" ({args.website})" if args.website else "")
        overview = f"{name}: what the company does, products, customers, size, headquarters"
        if research.returns_pages:
            searches = [
                research.search(overview, max_results=5),
                research.search(f"{args.company} news", max_results=5, news_days=180, grounded=False),
            ]
            if args.person:
                searches.append(research.search(f"{args.person} {args.company}", max_results=3, grounded=False))
        else:  # grounded answers only: one question covers the company and its news
            searches = [research.search(f"{overview}; and its most important news of the last six months", max_results=5)]
            if args.person:
                searches.append(research.search(f"Who is {args.person} at {args.company}? Role and background.", max_results=3))
        gathered = await asyncio.gather(*searches, return_exceptions=True)
        findings = [item for item in gathered if isinstance(item, Findings)]
        if not findings:
            raise ToolFailed(f"could not research {args.company}: {gathered[0]}")

        numbered = _number_sources(findings)
        brief = await _brief(router, args, findings, numbered)
        data: dict[str, object] = {
            "company": args.company,
            "brief": brief,
            "sources": [{"n": n, "title": link.title, "url": link.url} for n, link in enumerate(numbered, 1)],
        }
        if brief is None:  # the summarizer was unavailable: hand over the raw findings instead
            data["findings"] = [
                {
                    "answer": item.answer,
                    "results": [{"title": p.title, "url": p.url, "extract": clip(p.snippet, 400)} for p in item.pages],
                }
                for item in findings
            ]
        return ToolOutput(
            data=data,
            summary=f"Prospect brief for {args.company} from {plural(len(numbered), 'source')}"
            + ("" if brief else " (summary unavailable; raw findings returned)"),
            sources=tuple(numbered[:8]),
        )

    return [
        ToolDefinition(
            name="web_search",
            description=(
                "Search the public web. Returns an answer grounded in Google Search (when available) plus ranked "
                "pages with extracts. Cite the URLs you rely on."
            ),
            kind=ToolKind.READ,
            scope=ToolScope.READ,
            category=ToolCategory.INTELLIGENCE,
            input_model=WebSearchArgs,
            handler=web_search,
            timeout_seconds=60,
        ),
        ToolDefinition(
            name="research_prospect",
            description=(
                "Research a prospect company (and optionally a contact) on the public web and get a cited pre-call "
                "brief: overview, recent developments, likely priorities, talking points. Combine it with "
                "search_emails and search_knowledge_base for the rep's own history."
            ),
            kind=ToolKind.READ,
            scope=ToolScope.READ,
            category=ToolCategory.INTELLIGENCE,
            input_model=ResearchProspectArgs,
            handler=research_prospect,
            timeout_seconds=150,
        ),
    ]


def _number_sources(findings: list[Findings]) -> list[SourceLink]:
    seen: dict[str, SourceLink] = {}
    for item in findings:
        for link in item.links(limit=20):
            seen.setdefault(link.url, link)
    return list(seen.values())[:15]


async def _brief(
    router: ModelRouter, args: ResearchProspectArgs, findings: list[Findings], numbered: list[SourceLink]
) -> str | None:
    index = {link.url: n for n, link in enumerate(numbered, 1)}
    lines = [f"Company: {args.company}"]
    if args.website:
        lines.append(f"Website: {args.website}")
    if args.person:
        lines.append(f"Contact: {args.person}")
    if args.focus:
        lines.append(f"Rep's focus: {args.focus}")
    lines.append(f"Today: {date.today().isoformat()}")
    lines.append("\nFindings:")
    listed: set[str] = set()
    for item in findings:
        if item.answer:
            cited = ", ".join(f"[{index[link.url]}]" for link in item.answer_sources if link.url in index)
            lines.append(f"- Search answer {cited}: {clip(item.answer, 1_200)}")
        for page in item.pages:
            if page.url in index and page.url not in listed:
                listed.add(page.url)
                lines.append(f"[{index[page.url]}] {page.title} ({page.published or 'undated'}): {clip(page.snippet, 700)}")
    lines.append(
        "\nWrite the brief (at most 300 words) with these sections: Overview; Recent developments; Likely priorities "
        "and pain points; People (only if found); Talking points" + (" for the rep's focus" if args.focus else "")
        + "; Questions to ask."
    )
    task = TaskSpec(
        purpose="prospect_brief",
        system=_BRIEF_SYSTEM,
        messages=(Message(role=Role.USER, content="\n".join(lines)),),
        complexity=Complexity.LOW,
        max_output_tokens=900,
    )
    try:
        completion = await router.complete(task)
    except ProviderError as exc:
        logger.warning("prospect brief for %s failed: %s", args.company, exc)
        return None
    return completion.message.content.strip() or None
