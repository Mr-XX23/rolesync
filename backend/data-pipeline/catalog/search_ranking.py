"""Relevance ranking for catalog search.

BM25 over a product's fields, weighted by how much each field says about the product
(name and keywords count more than the description). Words that appear in most of the
tenant's catalog ("business", "solution") weigh little; rare, telling words ("invoicing")
decide the order. Products matching more of the query's telling words rank higher, and
results far below the best match are dropped instead of padding the list.

Pure functions (no database), so the ranking can be tested on its own.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Sequence
from uuid import UUID

FIELD_WEIGHTS: dict[str, float] = {
    "name": 3.0,
    "keywords": 2.5,
    "category": 2.0,
    "use_cases": 2.0,
    "value_proposition": 1.5,
    "target_industries": 1.2,
    "description": 1.0,
}
FIELD_LABELS = {
    "name": "name",
    "keywords": "keywords",
    "category": "category",
    "use_cases": "use cases",
    "value_proposition": "value proposition",
    "target_industries": "industries",
    "description": "description",
}
K1 = 1.2
B = 0.75
EXPANDED_TERM_WEIGHT = 0.4  # synonyms from query expansion help recall but never outrank the words typed
RELATIVE_CUTOFF = 0.25  # drop results scoring below this share of the best result

_WORD = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset(
    """a an and are as at be but by can do does for from has have how i in is it its me my of on or our so that the
    their them there these they this to up us was we what when where which who why will with you your about any all
    into more most other some such than then too very just also need needs want wants looking something get"""
    .split()
)


def stem(word: str) -> str:
    """Light suffix stripping so "invoice", "invoices" and "invoicing" match each other."""
    if len(word) <= 3 or word.isdigit():
        return word
    for suffix, replacement in (("ies", "y"), ("sses", "ss"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            if suffix == "s" and word.endswith("ss"):
                break
            word = word[: len(word) - len(suffix)] + replacement
            break
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]
    return word


def terms(text: str) -> list[str]:
    """Stemmed content words, in order (duplicates kept)."""
    return [stem(word) for word in _content_words(text)]


def _content_words(text: str) -> list[str]:
    return [word for word in _WORD.findall(text.lower()) if len(word) > 1 and word not in _STOP_WORDS]


@dataclass(frozen=True)
class SearchableProduct:
    product_id: UUID
    name: str = ""
    category: str = ""
    subcategory: str = ""
    keywords: Sequence[str] = ()
    use_cases: Sequence[str] = ()
    value_proposition: str = ""
    target_industries: Sequence[str] = ()
    description: str = ""
    skus: Sequence[str] = ()

    def fields(self) -> dict[str, list[str]]:
        return {
            "name": terms(self.name),
            "keywords": terms(" ".join(self.keywords)),
            "category": terms(f"{self.category} {self.subcategory}".replace("_", " ")),
            "use_cases": terms(" ".join(self.use_cases)),
            "value_proposition": terms(self.value_proposition),
            "target_industries": terms(" ".join(self.target_industries)),
            "description": terms(self.description),
        }


@dataclass(frozen=True)
class RankedProduct:
    product_id: UUID
    score: float
    matched_terms: list[str] = field(default_factory=list)
    rationale: str = ""


def rank_products(
    query: str,
    products: Iterable[SearchableProduct],
    *,
    expanded_terms: Sequence[str] = (),
    limit: int = 20,
) -> list[RankedProduct]:
    catalog = list(products)
    query_text = query.strip().lower()
    typed = list(dict.fromkeys(terms(query)))
    weights = {term: 1.0 for term in typed}
    surface: dict[str, str] = {}  # stemmed term -> the word as it was written, for explanations
    for word in _content_words(query):
        surface.setdefault(stem(word), word)
    for extra in expanded_terms:
        for word in _content_words(extra):
            weights.setdefault(stem(word), EXPANDED_TERM_WEIGHT)
            surface.setdefault(stem(word), word)
    if not catalog or (not weights and not query_text):
        return []

    indexed = [(product, product.fields()) for product in catalog]
    field_lengths = {name: [len(fields[name]) for _, fields in indexed] for name in FIELD_WEIGHTS}
    average_length = {name: (sum(lengths) / len(lengths)) or 1.0 for name, lengths in field_lengths.items()}
    document_frequency = Counter(
        term for _, fields in indexed for term in {t for tokens in fields.values() for t in tokens} if term in weights
    )
    total = len(indexed)

    def idf(term: str) -> float:
        df = document_frequency.get(term, 0)
        return math.log(1 + (total - df + 0.5) / (df + 0.5))

    query_mass = sum(idf(term) * weight for term, weight in weights.items() if weight == 1.0) or 1.0
    ranked: list[RankedProduct] = []
    for product, fields in indexed:
        counts = {name: Counter(tokens) for name, tokens in fields.items()}
        score = 0.0
        covered = 0.0
        contributions: list[tuple[float, str, str]] = []  # (points, term, best field)
        for term, weight in weights.items():
            weighted_tf = 0.0
            best_field, best_points = "", 0.0
            for name, field_weight in FIELD_WEIGHTS.items():
                tf = counts[name].get(term, 0)
                if not tf:
                    continue
                normalized = field_weight * tf / (1 - B + B * len(fields[name]) / average_length[name])
                weighted_tf += normalized
                if normalized > best_points:
                    best_field, best_points = name, normalized
            if weighted_tf == 0:
                continue
            points = weight * idf(term) * weighted_tf * (K1 + 1) / (weighted_tf + K1)
            score += points
            if weight == 1.0:
                covered += idf(term)
            contributions.append((points, term, best_field))

        exact_sku = query_text and any(query_text == sku.lower() for sku in product.skus)
        if exact_sku:
            score += 50.0
        elif query_text and len(typed) > 1 and query_text in product.name.lower():
            score += 5.0  # the whole phrase in the name
        if score <= 0:
            continue
        score *= 0.5 + 0.5 * min(1.0, covered / query_mass)  # favour matching more of what was asked
        contributions.sort(reverse=True)
        matched = [surface.get(term, term) for _, term, _ in contributions]
        reasons = [f"'{surface.get(term, term)}' in {FIELD_LABELS[name]}" for _, term, name in contributions[:3]]
        if exact_sku:
            reasons.insert(0, "exact SKU")
        ranked.append(
            RankedProduct(
                product_id=product.product_id,
                score=round(score, 2),
                matched_terms=matched[:5],
                rationale="Matched " + ", ".join(reasons),
            )
        )

    ranked.sort(key=lambda item: item.score, reverse=True)
    if ranked:
        floor = ranked[0].score * RELATIVE_CUTOFF
        ranked = [item for item in ranked if item.score >= floor]
    return ranked[:limit]
