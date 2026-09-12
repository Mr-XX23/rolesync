"""Semantic utility scorer - judges whether content is worth remembering.

The lexical checker only catches corrupted or repetitive text; it cannot tell a
useful sales document from an automated receipt. This scores content utility
with a small Gemini model (GOOGLE_GEMINI_MODE).

Two safety rules:
  * Runs in LOG-ONLY mode by default (see policy.py) - scores are recorded but
    nothing is rejected until a threshold has been validated against real data.
  * A scorer failure NEVER rejects. `ok=False` means "no signal", so an outage
    degrades to the lexical checks rather than silently dropping good documents.

Note this adds one LLM call per ingested document, so it is a real line item in
the ingestion cost model (see docs/billing/cost-model-and-credit-system.md).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

from module_1_document_processing.parsing.parsed_document import ParsedDocument
from module_2_memory_gatekeeper.policy import GatekeeperPolicy, load_policy

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
MAX_SCORED_CHARS = 4000

_PROMPT = """You score whether a document is worth storing in a sales team's knowledge base.

Useful (high score): product and pricing information, competitor or battlecard material,
case studies, security and compliance answers, contracts, meeting notes with decisions,
customer requirements, technical documentation.

Not useful (low score): automated notifications, delivery receipts, calendar invites with no
agenda, marketing spam, out-of-office replies, navigation boilerplate, duplicated headers,
or content with no reusable information.

Reply with ONLY a JSON object:
{"score": <number between 0 and 1>, "reason": "<short explanation, max 15 words>"}

Document category: %(category)s
Source: %(source)s
Content:
%(content)s
"""


@dataclass
class SemanticScore:
    score: float
    reason: str
    model: str
    ok: bool  # False = no usable signal; callers must not reject on this


class SemanticScorer:
    """Scores document utility with a small Gemini model."""

    def __init__(self, policy: Optional[GatekeeperPolicy] = None) -> None:
        self._policy = policy

    @property
    def policy(self) -> GatekeeperPolicy:
        return self._policy or load_policy()

    def available(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY", "").strip()) and requests is not None

    def score(self, document: ParsedDocument, category: str = "") -> SemanticScore:
        policy = self.policy
        model = policy.semantic_model

        if not policy.semantic_enabled:
            return SemanticScore(0.0, "semantic scoring disabled", model, ok=False)
        if not self.available():
            return SemanticScore(0.0, "GEMINI_API_KEY not set", model, ok=False)

        content = (document.text_content or "").strip()
        if not content:
            return SemanticScore(0.0, "no content to score", model, ok=False)

        prompt = _PROMPT % {
            "category": category or "unknown",
            "source": document.source or "unknown",
            "content": content[:MAX_SCORED_CHARS],
        }

        try:
            response = requests.post(
                f"{_GEMINI_BASE}/models/{model}:generateContent",
                headers={
                    "x-goog-api-key": os.environ.get("GEMINI_API_KEY", "").strip(),
                    "Content-Type": "application/json",
                },
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0,
                        "maxOutputTokens": 200,
                        "responseMimeType": "application/json",
                    },
                },
                timeout=policy.semantic_timeout_seconds,
            )
            if response.status_code != 200:
                print(f"[SemanticScorer] {model} HTTP {response.status_code}: {response.text[:200]}")
                return SemanticScore(0.0, f"scorer unavailable ({response.status_code})", model, ok=False)

            candidates = response.json().get("candidates") or []
            parts = (candidates[0].get("content", {}).get("parts") or []) if candidates else []
            raw = (parts[0].get("text") if parts else "") or ""
            return self._parse(raw, model)
        except Exception as err:
            print(f"[SemanticScorer] {model} request failed: {err}")
            return SemanticScore(0.0, "scorer request failed", model, ok=False)

    @staticmethod
    def _parse(raw: str, model: str) -> SemanticScore:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[-1] if "\n" in text else text
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]

        try:
            data = json.loads(text)
            score = float(data.get("score"))
        except (ValueError, TypeError, AttributeError):
            print(f"[SemanticScorer] Unparseable response: {raw[:160]}")
            return SemanticScore(0.0, "unparseable scorer response", model, ok=False)

        score = min(1.0, max(0.0, score))
        reason = str(data.get("reason", ""))[:200] or "no reason given"
        return SemanticScore(score, reason, model, ok=True)


semantic_scorer = SemanticScorer()
