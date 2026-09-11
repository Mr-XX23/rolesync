"""Tavily web search behind our own interface: ranked pages with text extracts."""

from __future__ import annotations

from dataclasses import dataclass

import httpx


class WebSearchError(Exception):
    """A search backend failed; the message is safe to show to the agent."""


@dataclass(frozen=True, slots=True)
class WebPage:
    title: str
    url: str
    snippet: str
    published: str | None = None


class TavilySearch:
    def __init__(
        self, *, api_key: str, http: httpx.AsyncClient, base_url: str = "https://api.tavily.com", timeout_seconds: float = 20.0
    ) -> None:
        self._api_key = api_key
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def search(self, query: str, *, max_results: int, news_days: int | None = None) -> list[WebPage]:
        body: dict[str, object] = {"query": query, "max_results": max_results, "search_depth": "basic", "include_answer": False}
        if news_days:
            body |= {"topic": "news", "days": news_days}
        try:
            response = await self._http.post(
                f"{self._base_url}/search",
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise WebSearchError(f"Tavily unreachable: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise WebSearchError(f"Tavily {response.status_code}: {response.text[:200]}")
        pages = []
        for item in response.json().get("results") or []:
            if isinstance(item, dict) and item.get("url"):
                pages.append(
                    WebPage(
                        title=str(item.get("title") or item["url"]),
                        url=str(item["url"]),
                        snippet=str(item.get("content") or ""),
                        published=item.get("published_date"),
                    )
                )
        return pages
