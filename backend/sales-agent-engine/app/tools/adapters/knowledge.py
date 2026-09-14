"""Knowledge-base tools over data-pipeline's knowledge vault (shared by the workspace).

Search uses data-pipeline's semantic search (``POST /knowledge-vault/search``: an embedded
query against the workspace's indexed passages, each with the wider context around it). When
that is unavailable, or finds nothing among the workspace's indexed documents (older documents
may have no vectors), it falls back to keyword retrieval here: rank documents by their sales
metadata, read the best candidates' text, and return the passages that match. data-pipeline
enforces workspace membership on every call.

``list_knowledge_documents`` shows every document whatever its state, for finding one to change
(changes are in ``knowledge_writes.py``).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from typing import Any, Literal, get_args
from uuid import UUID

from pydantic import Field

from app.platform.data_pipeline import DataPipelineClient, DataPipelineError
from app.tools.adapters.common import as_dict, clip, pipeline_failure, plural
from app.tools.registry import ToolDefinition
from app.tools.types import ToolCategory, ToolInput, ToolInputError, ToolInvocation, ToolKind, ToolOutput, ToolScope

logger = logging.getLogger(__name__)

KnowledgeCategory = Literal[
    "BATTLECARD",
    "PRICING_PACKAGING",
    "CASE_STUDY_ROI",
    "SECURITY_COMPLIANCE",
    "PRODUCT_SPEC",
    "CONTRACT_LEGAL",
    "GENERAL_RESOURCE",
]
CATEGORIES: tuple[str, ...] = get_args(KnowledgeCategory)
DocumentStatus = Literal["Indexed", "Parsing", "Error", "Rejected"]
# Where a document came from (data-pipeline's ``source``); connectors use their own name.
SOURCE_LABELS = {"USER_UPLOAD": "uploaded file", "URL_INGEST": "web page"}
_CANDIDATES = 6  # documents whose text is read per keyword search
_SEMANTIC_HITS_PER_RESULT = 4  # passages asked for per document wanted, before grouping by document
_CONTEXT_CHARS = 1_200
_SCAN_CHARS = 400_000  # of each document's text
_PASSAGE_CHARS = 700
_DOCUMENT_CHARS = 15_000

_WORD = re.compile(r"[a-z0-9][a-z0-9+&'-]*")
_STOP_WORDS = frozenset(
    "a an and are as at be but by can do does for from has have how i in is it its me my of on or our so that the "
    "their them there these they this to up us was we what when where which who why will with you your about "
    "any all into more most other some such than then too very just also get got".split()
)
_METADATA_WEIGHTS = (
    ("name", 3.0),
    ("sales_summary", 2.0),
    ("sales_tags", 2.0),
    ("target_competitor", 2.0),
    ("target_industry", 1.5),
    ("category", 1.0),
    ("preview", 1.0),
)


class SearchKnowledgeArgs(ToolInput):
    query: str = Field(min_length=2, max_length=300, description="What to look for, in plain words")
    category: str | None = Field(default=None, description="Optional: " + ", ".join(CATEGORIES))
    max_results: int = Field(default=5, ge=1, le=10)


class ReadKnowledgeDocumentArgs(ToolInput):
    doc_id: str = Field(min_length=3, max_length=64, description="doc_id from search_knowledge_base")
    question: str | None = Field(
        default=None, max_length=300, description="If the document is long, return the parts relevant to this"
    )


class ListKnowledgeDocumentsArgs(ToolInput):
    status: DocumentStatus | None = Field(
        default=None,
        description="Only documents in this state: Indexed (searchable), Parsing (being processed), Error or Rejected (not searchable; see problem)",
    )
    category: KnowledgeCategory | None = None
    search: str | None = Field(default=None, min_length=2, max_length=200, description="Words in the name, type, competitor, industry or tags")
    added_by_me: bool = Field(default=False, description="Only documents the rep added")
    limit: int = Field(default=20, ge=1, le=50)


def knowledge_tools(client: DataPipelineClient) -> list[ToolDefinition]:
    async def search_knowledge_base(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, SearchKnowledgeArgs)
        ctx = invocation.ctx
        category = args.category.strip().upper() if args.category else None
        if category and category not in CATEGORIES:
            category = None  # an unknown category would only hide documents
        query_terms = terms(args.query)
        try:
            documents = await client.list_documents(ctx.user_id, ctx.tenant_id, category=category)
        except DataPipelineError as exc:
            raise pipeline_failure(exc) from exc

        semantic = await semantic_search(ctx.user_id, ctx.tenant_id, args, documents)
        if semantic:
            return ToolOutput(
                data={"documents": semantic, "searched": len(documents), "method": "semantic"},
                summary=f"{plural(len(semantic), 'knowledge-base document')} matching '{args.query}'",
            )

        # Newest first when nothing in the metadata matches: their text may still.
        ranked = sorted(
            (doc for doc in documents if doc.get("doc_id")), key=lambda doc: metadata_score(doc, query_terms), reverse=True
        )[:_CANDIDATES]
        texts = await asyncio.gather(*(_text(client, ctx.user_id, ctx.tenant_id, doc["doc_id"]) for doc in ranked))
        results = []
        for doc, text in zip(ranked, texts, strict=True):
            passages = best_passages(text, query_terms, limit=2)
            score = metadata_score(doc, query_terms) + sum(passage_score(p, query_terms) for p in passages)
            if score > 0:
                results.append((score, _document(doc, passages)))
        results.sort(key=lambda item: item[0], reverse=True)
        found = [document for _, document in results[: args.max_results]]
        return ToolOutput(
            data={"documents": found, "searched": len(documents), "method": "keyword"},
            summary=f"{plural(len(found), 'knowledge-base document')} matching '{args.query}'",
        )

    async def semantic_search(user_id: Any, tenant_id: Any, args: SearchKnowledgeArgs, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Documents with their best-matching passages, best first; empty when semantic search can't help."""
        indexed = {str(doc["doc_id"]): doc for doc in documents if doc.get("doc_id")}
        if not indexed:
            return []
        try:
            hits = await client.search_knowledge(user_id, tenant_id, args.query, limit=min(50, args.max_results * _SEMANTIC_HITS_PER_RESULT))
        except DataPipelineError as exc:
            logger.warning("semantic knowledge search failed (%s); using keyword retrieval", exc)
            return []  # briefly unavailable: keyword retrieval still answers
        found: dict[str, dict[str, Any]] = {}
        for hit in hits or []:  # best first
            # A hit's doc_id is the pipeline's canonical id ("{workspace}:{source}:{id}"); the vault lists
            # documents by doc_ref_id. Connector documents are listed under the canonical id itself.
            doc = indexed.get(str(hit.get("doc_ref_id"))) or indexed.get(str(hit.get("doc_id")))
            if doc is None:
                continue  # not indexed any more, or outside the category asked for
            entry = found.get(str(doc["doc_id"]))
            if entry is None:
                if len(found) >= args.max_results:
                    continue
                score = hit.get("score")
                entry = found[str(doc["doc_id"])] = _document(doc, []) | {"score": round(float(score), 3) if score is not None else None}
            passage = clip(" ".join(str(hit.get("context") or hit.get("text") or "").split()), _CONTEXT_CHARS)
            if passage and passage not in entry["passages"] and len(entry["passages"]) < 2:
                entry["passages"].append(passage)
        if hits and not found and not args.category:
            # Worth seeing in the logs: hits that match no listed document mean the two ids disagree.
            logger.warning("semantic knowledge search returned %d hits but none matched an indexed document", len(hits))
        return list(found.values())

    async def read_knowledge_document(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, ReadKnowledgeDocumentArgs)
        ctx = invocation.ctx
        try:
            body = await client.document_text(ctx.user_id, ctx.tenant_id, args.doc_id)
        except DataPipelineError as exc:
            raise pipeline_failure(exc) from exc
        if body is None:
            raise ToolInputError(f"the workspace's knowledge base has no document '{args.doc_id}'")
        text = body.get("full_text") if isinstance(body.get("full_text"), str) else ""
        if len(text) <= _DOCUMENT_CHARS or not args.question:
            content = {"text": clip(text, _DOCUMENT_CHARS), "truncated": len(text) > _DOCUMENT_CHARS}
        else:
            content = {"passages": best_passages(text, terms(args.question), limit=8), "truncated": True}
        name = body.get("filename") or args.doc_id
        return ToolOutput(
            data={"doc_id": args.doc_id, "name": name, "category": body.get("category"), **content},
            summary=f"Read '{name}' ({plural(len(text), 'character')})",
        )

    async def list_knowledge_documents(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, ListKnowledgeDocumentsArgs)
        ctx = invocation.ctx
        try:
            documents = await client.list_documents(
                ctx.user_id, ctx.tenant_id, status=args.status, category=args.category, search=args.search, mine=args.added_by_me
            )
        except DataPipelineError as exc:
            raise pipeline_failure(exc) from exc
        listed = [vault_entry(doc, ctx.user_id) for doc in documents[: args.limit]]
        states = Counter(str(doc.get("status") or "Unknown") for doc in documents)
        needing_attention = states.get("Error", 0) + states.get("Rejected", 0)
        return ToolOutput(
            data={"documents": listed, "total": len(documents), "by_status": dict(states)},
            summary=f"{plural(len(documents), 'knowledge-base document')}"
            + (f", showing {len(listed)}" if len(listed) < len(documents) else "")
            + (f" ({needing_attention} not searchable)" if needing_attention else ""),
        )

    return [
        ToolDefinition(
            name="search_knowledge_base",
            description=(
                "Search the workspace's sales knowledge base (battlecards, pricing, case studies, security, product "
                "specs, contracts, and files the rep attached) by meaning. Returns matching documents with relevant passages."
            ),
            kind=ToolKind.READ,
            scope=ToolScope.READ,
            category=ToolCategory.KNOWLEDGE,
            input_model=SearchKnowledgeArgs,
            handler=search_knowledge_base,
            timeout_seconds=45,
        ),
        ToolDefinition(
            name="read_knowledge_document",
            description="Read one knowledge-base document (from search_knowledge_base).",
            kind=ToolKind.READ,
            scope=ToolScope.READ,
            category=ToolCategory.KNOWLEDGE,
            input_model=ReadKnowledgeDocumentArgs,
            handler=read_knowledge_document,
            timeout_seconds=45,
        ),
        ToolDefinition(
            name="list_knowledge_documents",
            description=(
                "List the workspace's knowledge-base documents newest first, in every state (Indexed, Parsing, Error, "
                "Rejected) with why a document isn't searchable, its classification, and whether the rep added it. "
                "Use it to find a document to change or delete; to find information use search_knowledge_base."
            ),
            kind=ToolKind.READ,
            scope=ToolScope.READ,
            category=ToolCategory.KNOWLEDGE,
            input_model=ListKnowledgeDocumentsArgs,
            handler=list_knowledge_documents,
            timeout_seconds=30,
        ),
    ]


def vault_entry(doc: dict[str, Any], user_id: UUID) -> dict[str, Any]:
    """A vault document as the agent sees it. Who added it shows only as ``added_by_me``, never as a person's id."""
    source = str(doc.get("source") or "")
    status = doc.get("status")
    entry = {
        "doc_id": doc.get("doc_id"),
        "name": doc.get("name"),
        "type": doc.get("type"),
        "status": status,
        "category": doc.get("category"),
        "competitor": doc.get("target_competitor"),
        "industry": doc.get("target_industry"),
        "tags": doc.get("sales_tags") or [],
        "summary": clip(doc.get("sales_summary"), 300),
        "chunks": doc.get("chunks"),
        "source": SOURCE_LABELS.get(source, f"synced from {source.replace('_', ' ').title()}" if source else None),
        "url": as_dict(doc.get("metadata")).get("target_url"),
        "added_by_me": str(doc.get("user_id")) == str(user_id),
        "classified_by": "hand" if doc.get("classifier_used") == "manual_user_override" else "classifier",
        "updated": doc.get("last_updated") or doc.get("created_at"),
    }
    if status in ("Error", "Rejected"):
        entry["problem"] = clip(doc.get("error_message"), 300) or None
    return {key: value for key, value in entry.items() if value not in (None, "")}


async def _text(client: DataPipelineClient, user_id: Any, tenant_id: Any, doc_id: str) -> str:
    try:
        body = await client.document_text(user_id, tenant_id, doc_id)
    except DataPipelineError:
        return ""  # one unreadable document shouldn't fail the whole search
    text = (body or {}).get("full_text")
    return text if isinstance(text, str) else ""


def _document(doc: dict[str, Any], passages: list[str]) -> dict[str, Any]:
    return {
        "doc_id": doc.get("doc_id"),
        "name": doc.get("name"),
        "category": doc.get("category"),
        "summary": clip(doc.get("sales_summary"), 400),
        "competitor": doc.get("target_competitor"),
        "industry": doc.get("target_industry"),
        "tags": doc.get("sales_tags") or [],
        "updated": doc.get("last_updated") or doc.get("created_at"),
        "passages": passages,
    }


def terms(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for word in _WORD.findall(text.lower()):
        if len(word) > 1 and word not in _STOP_WORDS:
            seen.setdefault(word, None)
    return list(seen)


def metadata_score(doc: dict[str, Any], query_terms: list[str]) -> float:
    fields = {
        "name": doc.get("name"),
        "sales_summary": doc.get("sales_summary"),
        "sales_tags": " ".join(str(tag) for tag in doc.get("sales_tags") or []),
        "target_competitor": doc.get("target_competitor"),
        "target_industry": doc.get("target_industry"),
        "category": str(doc.get("category") or "").replace("_", " "),
        "preview": (doc.get("metadata") or {}).get("preview_snippet") if isinstance(doc.get("metadata"), dict) else None,
    }
    score = 0.0
    for field, weight in _METADATA_WEIGHTS:
        words = set(terms(str(fields.get(field) or "")))
        score += weight * sum(1 for term in query_terms if term in words)
    return score


def passage_score(passage: str, query_terms: list[str]) -> float:
    words = _WORD.findall(passage.lower())
    matched = {term for term in query_terms if term in words}
    return 2.0 * len(matched) + 0.25 * sum(words.count(term) for term in matched)


def best_passages(text: str, query_terms: list[str], *, limit: int) -> list[str]:
    """The passages (about ``_PASSAGE_CHARS`` long) that best match, in document order."""
    if not text or not query_terms:
        return []
    windows: list[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", text[:_SCAN_CHARS]):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        if current and len(current) + len(paragraph) > _PASSAGE_CHARS:
            windows.append(current)
            current = ""
        current = f"{current} {paragraph}".strip()
        while len(current) > _PASSAGE_CHARS * 2:  # one huge paragraph: cut it into windows
            windows.append(current[:_PASSAGE_CHARS])
            current = current[_PASSAGE_CHARS:]
    if current:
        windows.append(current)
    scored = [(passage_score(window, query_terms), index) for index, window in enumerate(windows)]
    best = sorted((item for item in scored if item[0] > 0), reverse=True)[:limit]
    return [clip(windows[index], _PASSAGE_CHARS) for _, index in sorted(best, key=lambda item: item[1])]
