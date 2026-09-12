import os
import uuid
import re
import hashlib
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field

from module_1_document_processing.identity import bind_identity
from module_1_document_processing.workspace_access import WorkspaceAccess, require_workspace_member, require_writer

try:
    import pymongo
except ImportError:
    pymongo = None

from module_1_document_processing.parsing.parser_service import ParserService
from module_1_document_processing.classification.sales_classifier import SalesClassifier, VALID_SALES_CATEGORIES
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.raw_document_store import raw_document_store
from module_1_document_processing.pipeline.durable_queue import ingest_queue
from module_1_document_processing.pipeline.job_payloads import (
    JOB_DOCUMENT_INGEST,
    discard_staged_bytes,
    load_staged_bytes,
    stage_bytes,
)
from module_1_document_processing.pipeline import ingestion_guards as guards
from module_1_document_processing.pipeline.canonical_store import CanonicalStore
from module_1_document_processing.parsing.media_queue import MEDIA_PENDING
from module_3_batch_ingestion_vector.chunker import HierarchicalChunker
from module_3_batch_ingestion_vector.delta_checker import VersionedHashDB
from module_3_batch_ingestion_vector.embedding_worker import EmbeddingWorker
from module_3_batch_ingestion_vector.vector_store import VectorStore
from module_3_batch_ingestion_vector.pgvector_index import pgvector_index
from module_3_batch_ingestion_vector.ingestion_pipeline import BatchIngestionPipeline

# The knowledge vault is shared by a workspace, like the catalog. Every route requires the
# gateway-verified identity (X-User-Id) and active membership of the workspace in X-Tenant-Id
# (require_workspace_member); documents are looked up within that workspace only
# (_find_doc_record(doc_id, workspace_id)). The uploader is recorded as the document's user_id.
router = APIRouter(tags=["Knowledge Vault"], dependencies=[Depends(bind_identity)])

# Storage & Engine instances
vector_store = VectorStore()
parser_service = ParserService()
sales_classifier = SalesClassifier()
# Lineage for manual uploads, so they are tracked exactly like connector events.
canonical_store = CanonicalStore()
# Embeds search queries (RETRIEVAL_QUERY) for semantic lookup.
query_embedder = EmbeddingWorker()

# MongoDB initialization for Knowledge Documents & RAG configs with resilient in-memory fallback
MONGO_URI = os.environ.get("MONGODB_URI", "mongodb://mongodb:27017")
DB_NAME = os.environ.get("MONGODB_DB_NAME", "rolesync_rag")

_mongo_client = None
_docs_col = None
_config_col = None
_in_memory_docs: dict[str, dict[str, Any]] = {}
_in_memory_configs: dict[str, dict[str, Any]] = {}

if pymongo and MONGO_URI:
    try:
        _mongo_client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=500)
        _mongo_client.admin.command("ping")
        _db = _mongo_client[DB_NAME]
        _docs_col = _db["knowledge_documents"]
        _config_col = _db["knowledge_vault_configs"]
        _docs_col.create_index([("tenant_id", pymongo.ASCENDING), ("user_id", pymongo.ASCENDING), ("status", pymongo.ASCENDING)])
        _docs_col.create_index([("tenant_id", pymongo.ASCENDING), ("user_id", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)])
        _docs_col.create_index([("doc_id", pymongo.ASCENDING)], unique=True)
        # Non-unique on purpose: legacy duplicates may already share a content_hash, and a
        # unique index would fail to build / reject their writes. Used for fast dedup lookups.
        _docs_col.create_index([("tenant_id", pymongo.ASCENDING), ("content_hash", pymongo.ASCENDING)])
        _config_col.create_index([("tenant_id", pymongo.ASCENDING), ("user_id", pymongo.ASCENDING)], unique=True)
        print("[KnowledgeVault] Connected to MongoDB with compound indexes for knowledge_documents & configs.")
    except Exception as err:
        print(f"[KnowledgeVault] MongoDB offline / using in-memory store ({err})")
        _docs_col = None
        _config_col = None


# Models
class IngestUrlRequest(BaseModel):
    url: str
    title: Optional[str] = None
    category: Optional[str] = None
    target_competitor: Optional[str] = None


class UpdateClassificationRequest(BaseModel):
    category: Optional[str] = None
    target_competitor: Optional[str] = None
    target_industry: Optional[str] = None
    sales_summary: Optional[str] = None
    sales_tags: Optional[list[str]] = None


class RagConfigRequest(BaseModel):
    chunk_size: int = Field(default=512, ge=128, le=2048)
    overlap: int = Field(default=12, ge=0, le=30)
    embedding_engine: str = Field(default="RoleSync Vector Engine (1536-dim)")
    similarity_threshold: Optional[float] = Field(default=0.72, ge=0.0, le=1.0)


# Helper Functions
def _get_rag_config(tenant_id: str, user_id: str) -> dict[str, Any]:
    key = f"{tenant_id}:{user_id}"
    if key in _in_memory_configs:
        return _in_memory_configs[key]

    default_cfg = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "chunk_size": 512,
        "overlap": 12,
        "embedding_engine": "RoleSync Vector Engine (1536-dim)",
        "similarity_threshold": 0.72,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if _config_col is not None:
        try:
            cfg = _config_col.find_one({"tenant_id": tenant_id, "user_id": user_id})
            if cfg:
                cfg.pop("_id", None)
                _in_memory_configs[key] = cfg
                return cfg
        except Exception as e:
            print(f"[KnowledgeVault] Error reading config from MongoDB: {e}")

    _in_memory_configs[key] = default_cfg
    return default_cfg


def _save_rag_config(tenant_id: str, user_id: str, data: dict[str, Any]):
    data["tenant_id"] = tenant_id
    data["user_id"] = user_id
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    if _config_col is not None:
        try:
            _config_col.update_one(
                {"tenant_id": tenant_id, "user_id": user_id},
                {"$set": data},
                upsert=True,
            )
        except Exception as e:
            print(f"[KnowledgeVault] Error saving config to MongoDB: {e}")

    key = f"{tenant_id}:{user_id}"
    _in_memory_configs[key] = data


def _save_doc_record(doc: dict[str, Any]):
    doc_id = doc["doc_id"]
    if _docs_col is not None:
        try:
            _docs_col.update_one({"doc_id": doc_id}, {"$set": doc}, upsert=True)
        except Exception as e:
            print(f"[KnowledgeVault] Error saving doc to MongoDB: {e}")
    _in_memory_docs[doc_id] = doc


def _find_doc_record(doc_id: str, tenant_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Look up a document. When tenant_id is given, the document must belong to
    that tenant or None is returned — request handlers MUST pass it to prevent
    cross-tenant access by document id. Internal pipeline callers omit it."""
    if _docs_col is not None:
        try:
            query: dict[str, Any] = {"doc_id": doc_id}
            if tenant_id is not None:
                query["tenant_id"] = tenant_id
            doc = _docs_col.find_one(query)
            if doc:
                doc.pop("_id", None)
                return doc
            if tenant_id is not None:
                return None
        except Exception as e:
            print(f"[KnowledgeVault] Error reading doc from MongoDB: {e}")
    doc = _in_memory_docs.get(doc_id)
    if doc is not None and tenant_id is not None and doc.get("tenant_id") != tenant_id:
        return None
    return doc


def _list_doc_records(tenant_id: str, user_id: str = "") -> list[dict[str, Any]]:
    if _docs_col is not None:
        try:
            query: dict[str, Any] = {"tenant_id": tenant_id}
            if user_id:
                query["user_id"] = user_id
            cursor = _docs_col.find(query).sort("created_at", -1)
            docs = []
            for d in cursor:
                d.pop("_id", None)
                docs.append(d)
            return docs
        except Exception as e:
            print(f"[KnowledgeVault] Error listing docs from MongoDB: {e}")

    results = [
        d for d in _in_memory_docs.values()
        if d.get("tenant_id") == tenant_id and (not user_id or d.get("user_id") == user_id)
    ]
    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return results


def _is_healthy_doc(doc: dict[str, Any]) -> bool:
    """A document is 'healthy' once it is indexed with at least one vector chunk. An errored,
    still-parsing, or 0-chunk document is not — re-uploading it should repair it in place
    rather than leave a broken duplicate row behind."""
    return doc.get("status") == "Indexed" and int(doc.get("chunks", 0) or 0) > 0


def _find_doc_by_content_hash(tenant_id: str, content_hash: str) -> Optional[dict[str, Any]]:
    """Returns an existing document in this workspace whose raw bytes hash to the same value,
    or None. Used to stop the same file from being ingested as a brand-new row."""
    if not content_hash:
        return None
    if _docs_col is not None:
        try:
            doc = _docs_col.find_one({"tenant_id": tenant_id, "content_hash": content_hash})
            if doc:
                doc.pop("_id", None)
                return doc
            return None
        except Exception as e:
            print(f"[KnowledgeVault] Error looking up content_hash in MongoDB: {e}")
    for d in _in_memory_docs.values():
        if d.get("tenant_id") == tenant_id and d.get("content_hash") == content_hash:
            return d
    return None


def _find_doc_by_url(tenant_id: str, url: str) -> Optional[dict[str, Any]]:
    """Returns an existing URL document in this workspace for the same target URL, or None,
    so re-ingesting a URL refreshes the same row instead of creating a duplicate."""
    if not url:
        return None
    if _docs_col is not None:
        try:
            doc = _docs_col.find_one({"tenant_id": tenant_id, "metadata.target_url": url})
            if doc:
                doc.pop("_id", None)
                return doc
            return None
        except Exception as e:
            print(f"[KnowledgeVault] Error looking up target_url in MongoDB: {e}")
    for d in _in_memory_docs.values():
        if d.get("tenant_id") == tenant_id and (d.get("metadata") or {}).get("target_url") == url:
            return d
    return None


def _dedup_group_key(doc: dict[str, Any]) -> str:
    """Reconciliation grouping key: exact content hash when present, otherwise a conservative
    (name, size, type) fingerprint for legacy rows uploaded before hashing existed."""
    ch = doc.get("content_hash")
    if ch:
        return f"hash::{ch}"
    return f"legacy::{doc.get('name', '')}::{doc.get('size_bytes', 0)}::{doc.get('type', '')}"


def _dedup_keeper_rank(doc: dict[str, Any]) -> tuple:
    """Ranks the copies in a duplicate group; the highest-ranked copy is kept. Prefer an
    indexed doc, then the one with the most chunks, then the most recently created."""
    return (
        1 if doc.get("status") == "Indexed" else 0,
        int(doc.get("chunks", 0) or 0),
        doc.get("created_at", "") or "",
    )


def plan_deduplication(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pure planning step: groups documents and, for each group with more than one copy,
    returns which copy to keep and which to remove. No side effects — safe to preview."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for d in docs:
        groups.setdefault(_dedup_group_key(d), []).append(d)

    plan: list[dict[str, Any]] = []
    for _key, items in groups.items():
        if len(items) < 2:
            continue
        ordered = sorted(items, key=_dedup_keeper_rank, reverse=True)
        keeper, losers = ordered[0], ordered[1:]
        plan.append({
            "name": keeper.get("name"),
            "kept_doc_id": keeper.get("doc_id"),
            "kept_chunks": int(keeper.get("chunks", 0) or 0),
            "removed": [
                {
                    "doc_id": l.get("doc_id"),
                    "chunks": int(l.get("chunks", 0) or 0),
                    "status": l.get("status"),
                }
                for l in losers
            ],
        })
    return plan


def _delete_doc_record(doc_id: str):
    # Read the record before removing it: the chunk fingerprints and the lineage
    # row are keyed by the canonical id (tenant:source:doc_id), not the short id.
    _record = _find_doc_record(doc_id) or {}
    _tenant = _record.get("tenant_id", "")
    _source = _record.get("source", "USER_UPLOAD")
    _canonical_id = f"{_tenant}:{_source}:{doc_id}" if _tenant else doc_id

    if _docs_col is not None:
        try:
            _docs_col.delete_one({"doc_id": doc_id})
        except Exception as e:
            print(f"[KnowledgeVault] Error deleting doc from MongoDB: {e}")
    _in_memory_docs.pop(doc_id, None)
    vector_store.delete_by_doc_id(doc_id)
    if vector_store._collection is not None:
        try:
            vector_store._collection.delete_many({
                "$or": [
                    {"doc_id": doc_id},
                    {"doc_id": {"$regex": re.escape(doc_id) + "$"}},
                    {"vector_id": {"$regex": re.escape(doc_id)}},
                ]
            })
        except Exception as e:
            print(f"[KnowledgeVault] Error purging mongo vectors: {e}")

    # Clearing the chunk fingerprints is essential. Leaving them behind makes the
    # delta check treat a later re-upload of the same file as "unchanged", so it
    # skips embedding entirely and the document indexes with zero chunks.
    try:
        hash_db = VersionedHashDB()
        for key in {_canonical_id, doc_id}:
            hash_db.clear_document_hashes(key)
    except Exception as e:
        print(f"[KnowledgeVault] Error clearing chunk hashes for {doc_id}: {e}")

    # Tombstone the lineage rather than erasing the audit trail.
    try:
        canonical_store.mark_status(_canonical_id, "DELETED")
    except Exception as e:
        print(f"[KnowledgeVault] Error tombstoning lineage for {doc_id}: {e}")


def _process_document_background(
    doc_id: str,
    tenant_id: str,
    user_id: str,
    raw_bytes: bytes,
    filename: str,
    mime_type: str,
    source: str,
    user_override_category: Optional[str] = None,
    user_override_competitor: Optional[str] = None,
):
    """
    Parses document through ParserService (LlamaParse/LlamaIndex with local OCR fallback),
    runs SalesClassifier (OpenRouter AI with local heuristic fallback) to categorize the collateral,
    and processes through BatchIngestionPipeline using active RAG parameters.
    """
    try:
        # 1. Read current workspace RAG config
        cfg = _get_rag_config(tenant_id, user_id)
        chunk_size = int(cfg.get("chunk_size", 512))
        overlap = int(cfg.get("overlap", 12))
        embedding_engine = cfg.get("embedding_engine", "RoleSync Vector Engine (1536-dim)")

        # 2. Build CanonicalEvent for ParserService
        event = CanonicalEvent(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            event_type=EventType.CREATE,
            source=source,
            tenant_id=tenant_id,
            user_id=user_id,
            external_id=doc_id,
            raw_ref={},
            acl=[f"user:{user_id}", f"tenant:{tenant_id}"],
            metadata={"name": filename, "mime_type": mime_type, "title": filename},
        )

        # 2b. Record lineage so manual uploads are tracked exactly like connector events.
        canonical_store.record_event(event, status="STAGED")

        # 3. Parse via ParserService (handles MIME routing, LlamaParse/LlamaIndex, DirectTextParser)
        parsed_doc = parser_service.parse_event(event, raw_bytes=raw_bytes)
        print(f"[KnowledgeVault] Parsed {doc_id} with parser={parsed_doc.parser_used}, status={parsed_doc.parse_status}")

        # Audio/video is stored but cannot be indexed until transcription exists.
        if parsed_doc.parse_status == MEDIA_PENDING:
            canonical_store.record_event(event, status="MEDIA_PENDING")
            print(f"[KnowledgeVault] Media parked for {doc_id} (transcription not implemented).")
            record = _find_doc_record(doc_id)
            if record:
                record["status"] = "Rejected"
                record["chunks"] = 0
                record["error_message"] = guards.MEDIA_PENDING_MESSAGE
                record["last_updated"] = datetime.now(timezone.utc).isoformat()
                _save_doc_record(record)
            return

        if parsed_doc.parse_status == "FAILED":
            canonical_store.record_event(event, status="PARSED_FAILED")
            print(f"[KnowledgeVault] Parse failed for {doc_id}: {parsed_doc.metadata.get('error', 'unknown')}")
            record = _find_doc_record(doc_id)
            if record:
                record["status"] = "Error"
                record["error_message"] = guards.PARSE_FAILED_MESSAGE
                record["last_updated"] = datetime.now(timezone.utc).isoformat()
                _save_doc_record(record)
            return

        canonical_store.record_event(event, status="PARSED_SUCCESS")

        # 3b. Memory gatekeeper - the same quality gate the connector path applies.
        # Manual uploads previously bypassed this entirely.
        gate = guards.evaluate_gatekeeper(parsed_doc)
        if gate.decision != "ACCEPTED":
            canonical_store.record_event(event, status=f"GATEKEEPER_{gate.decision}")
            print(f"[KnowledgeVault] Gatekeeper {gate.decision} for {doc_id}: {gate.reason}")
            record = _find_doc_record(doc_id)
            if record:
                record["status"] = "Rejected"
                record["chunks"] = 0
                record["error_message"] = guards.gatekeeper_message(gate)
                record["last_updated"] = datetime.now(timezone.utc).isoformat()
                _save_doc_record(record)
            return

        canonical_store.record_event(event, status="GATEKEEPER_ACCEPTED")

        # 4. Classify document into sales taxonomy (Battlecards, Pricing, Case Studies, etc.)
        classification = sales_classifier.classify(
            filename=filename,
            mime_type=mime_type,
            text_content=parsed_doc.text_content or "",
            user_override_category=user_override_category,
            user_override_competitor=user_override_competitor,
        )
        print(f"[KnowledgeVault] Classified {doc_id} -> Category: {classification.category}, Competitor: {classification.target_competitor}, via {classification.classifier_used}")

        # 4b. Enrich parsed_doc metadata so EVERY chunk inherits doc_ref_id, category, and sales taxonomy
        parsed_doc.metadata.update({
            "doc_ref_id": doc_id,
            "parent_doc_id": doc_id,
            "category": classification.category,
            "document_type": classification.category,
            "target_competitor": classification.target_competitor,
            "target_industry": classification.target_industry,
            "sales_summary": classification.sales_summary,
            "sales_tags": classification.sales_tags,
            "confidence_score": classification.confidence_score,
            "classifier_used": classification.classifier_used,
        })

        # 4c. Persist raw/full document in dedicated raw_documents collection and storage volume
        raw_document_store.save_raw_document(
            doc_ref_id=doc_id,
            tenant_id=tenant_id,
            user_id=user_id,
            filename=filename,
            mime_type=mime_type,
            full_text_content=parsed_doc.text_content or "",
            raw_bytes=raw_bytes,
            category=classification.category,
            document_type=classification.category,
            target_competitor=classification.target_competitor,
            target_industry=classification.target_industry,
            sales_summary=classification.sales_summary,
            sales_tags=classification.sales_tags,
            total_chunks=0,
            parser_used=parsed_doc.parser_used,
            parse_status=parsed_doc.parse_status,
            metadata=parsed_doc.metadata,
            source=source,
        )

        # 5. Hierarchical Chunker calibrated with active RAG parameters
        chunk_overlap = max(0, int(chunk_size * (overlap / 100.0)))
        chunker = HierarchicalChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        embedding_worker = EmbeddingWorker(model_name=embedding_engine)
        batch_pipeline = BatchIngestionPipeline(
            chunker=chunker,
            embedding_worker=embedding_worker,
        )

        # 6. Process through the batch ingestion pipeline (chunking, delta check, embedding, vector store upsert)
        written_count = batch_pipeline.process_document(parsed_doc)

        # 6b. Update raw_document_store with generated chunk IDs
        chunk_ids = [f"{parsed_doc.doc_id}_chunk_{i}" for i in range(written_count)]
        raw_document_store.update_chunks(doc_id, total_chunks=written_count, chunk_ids=chunk_ids)

        # 6c. A document that produced no vector chunks was parsed to empty text (image-only
        # PDF, blank file, or a transient parser miss). Flag it as an error instead of leaving
        # a "healthy" Indexed row with 0 chunks — re-uploading the same file repairs it in place.
        if written_count <= 0:
            record = _find_doc_record(doc_id)
            if record:
                record["status"] = "Error"
                record["chunks"] = 0
                record["error_message"] = guards.NO_CONTENT_MESSAGE
                record["last_updated"] = datetime.now(timezone.utc).isoformat()
                _save_doc_record(record)
            print(f"[KnowledgeVault] {doc_id} produced 0 chunks; marked as Error (no extractable text).")
            return

        # 7. Update document record to Indexed with full sales intelligence metadata
        record = _find_doc_record(doc_id)
        if record:
            record["status"] = "Indexed"
            record["doc_ref_id"] = doc_id
            record["chunks"] = written_count
            record["category"] = classification.category
            record["document_type"] = classification.category
            record["target_competitor"] = classification.target_competitor
            record["target_industry"] = classification.target_industry
            record["sales_summary"] = classification.sales_summary
            record["sales_tags"] = classification.sales_tags
            record["classifier_used"] = classification.classifier_used
            record["confidence_score"] = classification.confidence_score
            record["word_count"] = len((parsed_doc.text_content or "").split())
            record["character_count"] = len(parsed_doc.text_content or "")
            record["has_raw_document"] = True
            record["last_updated"] = datetime.now(timezone.utc).isoformat()
            if "metadata" not in record:
                record["metadata"] = {}
            record["metadata"]["doc_ref_id"] = doc_id
            record["metadata"]["category"] = classification.category
            record["metadata"]["document_type"] = classification.category
            record["metadata"]["target_competitor"] = classification.target_competitor
            record["metadata"]["target_industry"] = classification.target_industry
            record["metadata"]["embedding_model"] = embedding_engine
            record["metadata"]["parser_used"] = parsed_doc.parser_used
            record["metadata"]["sales_classification"] = classification.to_dict()
            record["metadata"]["preview_snippet"] = (parsed_doc.text_content[:240] if parsed_doc.text_content else "").strip()
            _save_doc_record(record)

        canonical_store.record_event(event, status="VECTOR_STORE_INDEXED")
        print(f"[KnowledgeVault] Successfully indexed {doc_id} via BatchIngestionPipeline with {written_count} chunks.")

    except Exception as err:
        # The real error is logged; the user sees a generic, actionable message.
        print(f"[KnowledgeVault] Pipeline failure for {doc_id}: {err}")
        record = _find_doc_record(doc_id)
        if record:
            record["status"] = "Error"
            record["error_message"] = guards.PROCESSING_FAILED_MESSAGE
            record["last_updated"] = datetime.now(timezone.utc).isoformat()
            _save_doc_record(record)


# Endpoints
@router.get("/knowledge-vault/stats")
def get_vault_stats(access: WorkspaceAccess = Depends(require_workspace_member)):
    """Aggregated statistics across the workspace's knowledge documents, vector chunks, and sales taxonomy categories."""
    docs = _list_doc_records(access.workspace_id)
    total_docs = len(docs)
    total_chunks = sum(d.get("chunks", 0) for d in docs)
    total_bytes = sum(d.get("size_bytes", 0) for d in docs)
    sources = set(d.get("source", "USER_UPLOAD") for d in docs) if total_docs > 0 else set()

    # Calculate category counts
    category_counts = {cat: 0 for cat in VALID_SALES_CATEGORIES}
    for d in docs:
        c = d.get("category", "GENERAL_RESOURCE")
        if c in category_counts:
            category_counts[c] += 1
        else:
            category_counts["GENERAL_RESOURCE"] += 1

    return {
        "status": "success",
        "stats": {
            "total_documents": total_docs,
            "total_chunks": total_chunks,
            "total_size_bytes": total_bytes,
            "active_sources_count": len(sources),
            "vector_backend": (
                "pgvector (HNSW)"
                if pgvector_index is not None and pgvector_index.available()
                else "MongoDB / In-Memory"
            ),
            "indexed_count": sum(1 for d in docs if d.get("status") == "Indexed"),
            "parsing_count": sum(1 for d in docs if d.get("status") == "Parsing"),
            "error_count": sum(1 for d in docs if d.get("status") == "Error"),
            "category_counts": category_counts,
        },
    }


@router.get("/knowledge-vault/documents")
def list_documents(
    status: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    mine: bool = False,
    access: WorkspaceAccess = Depends(require_workspace_member),
):
    """Lists the workspace's knowledge documents (``mine=true``: only the caller's uploads) with status, sales category filtering, and multi-field search."""
    docs = _list_doc_records(access.workspace_id, access.user_id if mine else "")

    if status and status.lower() != "all":
        docs = [d for d in docs if d.get("status", "").lower() == status.lower()]

    if category and category.lower() != "all":
        docs = [d for d in docs if d.get("category", "GENERAL_RESOURCE").upper() == category.upper()]

    if search:
        s = search.lower()
        docs = [
            d for d in docs
            if s in d.get("name", "").lower()
            or s in d.get("type", "").lower()
            or s in d.get("category", "").lower()
            or s in (d.get("target_competitor") or "").lower()
            or s in (d.get("target_industry") or "").lower()
            or any(s in str(t).lower() for t in d.get("sales_tags", []))
        ]

    return {
        "status": "success",
        "count": len(docs),
        "documents": docs,
    }



def _queue_document_job(
    background_tasks: BackgroundTasks,
    *,
    doc_id: str,
    tenant_id: str,
    user_id: str,
    raw_bytes: bytes,
    filename: str,
    mime_type: str,
    source: str,
    user_override_category: Optional[str] = None,
    user_override_competitor: Optional[str] = None,
) -> None:
    """Hand parsing and indexing to the durable queue.

    The bytes are written to the raw object store *before* this returns, so the
    "queued for parsing" answer the caller gets is backed by something that
    survives a restart. FastAPI BackgroundTasks remains only as the fallback for
    when nothing durable is reachable - the old behaviour, not a silent loss.
    """
    staged_ref = stage_bytes(tenant_id, doc_id, raw_bytes, content_type=mime_type)
    if staged_ref:
        ingest_queue.enqueue(
            JOB_DOCUMENT_INGEST,
            {
                "doc_id": doc_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "filename": filename,
                "mime_type": mime_type,
                "source": source,
                "staged_ref": staged_ref,
                "user_override_category": user_override_category,
                "user_override_competitor": user_override_competitor,
            },
        )
        return

    print(f"[KnowledgeVault] Could not stage {doc_id}; processing in-process instead.")
    background_tasks.add_task(
        _process_document_background,
        doc_id=doc_id,
        tenant_id=tenant_id,
        user_id=user_id,
        raw_bytes=raw_bytes,
        filename=filename,
        mime_type=mime_type,
        source=source,
        user_override_category=user_override_category,
        user_override_competitor=user_override_competitor,
    )


def process_document_job(payload: dict) -> None:
    """Queue handler: reload the staged bytes and run the existing pipeline.

    Raises on failure so the queue retries and, after the last attempt, keeps the
    job in the dead-letter list instead of dropping it.
    """
    staged_ref = payload.get("staged_ref") or ""
    raw_bytes = load_staged_bytes(staged_ref)
    if raw_bytes is None:
        raise RuntimeError(f"Staged bytes missing for {payload.get('doc_id')} ({staged_ref})")

    try:
        _process_document_background(
            doc_id=payload.get("doc_id", ""),
            tenant_id=payload.get("tenant_id", ""),
            user_id=payload.get("user_id", ""),
            raw_bytes=raw_bytes,
            filename=payload.get("filename", ""),
            mime_type=payload.get("mime_type", ""),
            source=payload.get("source", "USER_UPLOAD"),
            user_override_category=payload.get("user_override_category"),
            user_override_competitor=payload.get("user_override_competitor"),
        )
    finally:
        discard_staged_bytes(staged_ref)


@router.post("/knowledge-vault/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    category: Optional[str] = Form(default=None),
    target_competitor: Optional[str] = Form(default=None),
    access: WorkspaceAccess = Depends(require_workspace_member),
):
    """Uploads a single file (PDF, CSV, TXT, DOCX, PPTX, XLSX, MD, JSON), validates <=25MB, runs SalesClassifier, and processes chunks via ParserService and BatchIngestionPipeline."""
    require_writer(access)
    filename = file.filename or "uploaded_file"

    # Read first so type, size and malware checks all run against the real bytes.
    try:
        content_bytes = await file.read()
    except Exception as err:
        print(f"[KnowledgeVault] Failed reading upload '{filename}': {err}")
        raise HTTPException(
            status_code=400,
            detail="We could not read that file. Please try uploading it again.",
        )

    size_bytes = len(content_bytes or b"")

    # The same guards every ingestion path runs: extension, size, malware/DLP.
    try:
        file_ext = guards.validate_upload(filename, size_bytes)
        guards.scan_content(content_bytes, filename)
    except guards.IngestionRejected as rejected:
        raise HTTPException(status_code=rejected.status_code, detail=rejected.message)

    # Content-addressed de-duplication: the same file must not create a second row.
    content_hash = hashlib.sha256(content_bytes).hexdigest()
    existing = _find_doc_by_content_hash(access.workspace_id, content_hash)
    if existing is not None and _is_healthy_doc(existing):
        # Already indexed — skip the duplicate and hand the caller back the original.
        return {
            "status": "duplicate",
            "message": (
                f"'{existing.get('name', filename)}' is already in your Knowledge Vault "
                f"({int(existing.get('chunks', 0) or 0)} chunks indexed). Skipped duplicate upload."
            ),
            "document": existing,
        }

    now_str = datetime.now(timezone.utc).isoformat()
    reused_existing = existing is not None
    if reused_existing:
        # A prior attempt exists but never indexed cleanly (errored / 0 chunks / stuck parsing).
        # Repair it in place under its original id instead of creating another duplicate row.
        doc_id = existing["doc_id"]
        created_at = existing.get("created_at", now_str)
        owner_id = existing.get("user_id") or access.user_id
        vector_store.delete_by_doc_id(doc_id)
    else:
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        created_at = now_str
        owner_id = access.user_id

    # Pre-classify with filename to provide immediate UI feedback while parsing in background
    prelim_classification = sales_classifier.classify(
        filename=filename,
        mime_type=file.content_type or "application/octet-stream",
        text_content=filename,
        user_override_category=category,
        user_override_competitor=target_competitor,
    )

    doc_record = {
        "doc_id": doc_id,
        "name": filename,
        "type": file_ext,
        "size_bytes": size_bytes,
        "chunks": 0,
        "status": "Parsing",
        "category": prelim_classification.category,
        "target_competitor": prelim_classification.target_competitor,
        "target_industry": prelim_classification.target_industry,
        "sales_summary": prelim_classification.sales_summary,
        "sales_tags": prelim_classification.sales_tags,
        "classifier_used": prelim_classification.classifier_used,
        "confidence_score": prelim_classification.confidence_score,
        "created_at": created_at,
        "last_updated": now_str,
        "tenant_id": access.workspace_id,
        "user_id": owner_id,
        "content_hash": content_hash,
        "source": "USER_UPLOAD",
        "metadata": {
            "content_type": file.content_type,
            "filename": filename,
            "preview_snippet": f"Ingesting {filename} ({size_bytes} bytes)...",
            "sales_classification": prelim_classification.to_dict(),
        },
    }
    _save_doc_record(doc_record)

    # Queue background parsing & vector ingestion with SalesClassifier
    _queue_document_job(
        background_tasks,
        doc_id=doc_id,
        tenant_id=access.workspace_id,
        user_id=owner_id,
        raw_bytes=content_bytes,
        filename=filename,
        mime_type=file.content_type or "application/octet-stream",
        source="USER_UPLOAD",
        user_override_category=category,
        user_override_competitor=target_competitor,
    )

    return {
        "status": "success",
        "message": (
            f"Existing document '{filename}' is being re-processed to repair its index."
            if reused_existing
            else f"File '{filename}' queued for parsing, classification, and vector embedding."
        ),
        "document": doc_record,
    }


@router.post("/knowledge-vault/ingest-url")
def ingest_url(
    req: IngestUrlRequest,
    background_tasks: BackgroundTasks,
    access: WorkspaceAccess = Depends(require_workspace_member),
):
    """Ingests text content from an external webpage URL and runs SalesClassifier."""
    require_writer(access)
    url = req.url.strip()
    if not re.match(r"^https?://[^\s/$.?#].[^\s]*$", url, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Invalid URL format. Must start with http:// or https://")

    # Fetch webpage content safely. A failed fetch is reported to the caller instead
    # of silently indexing a placeholder string as though it were real content.
    try:
        req_obj = urllib.request.Request(
            url,
            headers={"User-Agent": "RoleSync-Knowledge-Crawler/1.0 (+https://rolesync.ai)"},
        )
        with urllib.request.urlopen(req_obj, timeout=12) as response:
            raw_bytes = response.read(guards.MAX_URL_FETCH_BYTES + 1)
        if len(raw_bytes) > guards.MAX_URL_FETCH_BYTES:
            raw_bytes = raw_bytes[: guards.MAX_URL_FETCH_BYTES]
        raw_html = raw_bytes.decode("utf-8", errors="replace")
    except Exception as err:
        print(f"[KnowledgeVault] URL fetch failed for {url}: {err}")
        raise HTTPException(status_code=502, detail=guards.URL_FETCH_FAILED_MESSAGE)

    # Basic HTML clean up (strip script, style, and HTML tags)
    cleaned_text = re.sub(r"<(script|style).*?</\1>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
    cleaned_text = re.sub(r"<[^<]+?>", " ", cleaned_text)
    cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip()

    if not cleaned_text:
        raise HTTPException(
            status_code=422,
            detail="That page did not contain any readable text to index.",
        )

    now_str = datetime.now(timezone.utc).isoformat()
    doc_name = req.title.strip() if req.title else url
    content_bytes = cleaned_text.encode("utf-8", errors="replace")

    # Crawled pages are untrusted input and run the same scan as uploaded files.
    try:
        guards.scan_content(content_bytes, doc_name)
    except guards.IngestionRejected as rejected:
        raise HTTPException(status_code=rejected.status_code, detail=rejected.message)

    content_hash = hashlib.sha256(content_bytes).hexdigest()

    # Re-ingesting the same URL refreshes the existing row instead of creating a duplicate.
    existing = _find_doc_by_url(access.workspace_id, url)
    reused_existing = existing is not None
    if reused_existing:
        doc_id = existing["doc_id"]
        created_at = existing.get("created_at", now_str)
        owner_id = existing.get("user_id") or access.user_id
        vector_store.delete_by_doc_id(doc_id)
    else:
        doc_id = f"url_{uuid.uuid4().hex[:12]}"
        created_at = now_str
        owner_id = access.user_id

    prelim_classification = sales_classifier.classify(
        filename=doc_name,
        mime_type="text/html",
        text_content=cleaned_text[:2000],
        user_override_category=req.category,
        user_override_competitor=req.target_competitor,
    )

    doc_record = {
        "doc_id": doc_id,
        "name": doc_name,
        "type": "URL",
        "size_bytes": len(content_bytes),
        "chunks": 0,
        "status": "Parsing",
        "category": prelim_classification.category,
        "target_competitor": prelim_classification.target_competitor,
        "target_industry": prelim_classification.target_industry,
        "sales_summary": prelim_classification.sales_summary,
        "sales_tags": prelim_classification.sales_tags,
        "classifier_used": prelim_classification.classifier_used,
        "confidence_score": prelim_classification.confidence_score,
        "created_at": created_at,
        "last_updated": now_str,
        "tenant_id": access.workspace_id,
        "user_id": owner_id,
        "content_hash": content_hash,
        "source": "URL_INGEST",
        "metadata": {
            "target_url": url,
            "category": prelim_classification.category,
            "preview_snippet": cleaned_text[:240].strip(),
            "sales_classification": prelim_classification.to_dict(),
        },
    }
    _save_doc_record(doc_record)

    # Queue background processing
    _queue_document_job(
        background_tasks,
        doc_id=doc_id,
        tenant_id=access.workspace_id,
        user_id=owner_id,
        raw_bytes=content_bytes,
        filename=doc_name,
        mime_type="text/html",
        source="URL_INGEST",
        user_override_category=req.category,
        user_override_competitor=req.target_competitor,
    )

    return {
        "status": "success",
        "message": (
            f"URL '{url}' is being re-crawled to refresh the existing document."
            if reused_existing
            else f"URL '{url}' queued for extraction and vector embedding."
        ),
        "document": doc_record,
    }


@router.patch("/knowledge-vault/documents/{doc_id}/sales-classification")
def update_sales_classification(
    doc_id: str,
    req: UpdateClassificationRequest,
    access: WorkspaceAccess = Depends(require_workspace_member),
):
    """Allows a salesperson to manually update or override the sales taxonomy category, target competitor, tags, or summary."""
    require_writer(access)
    doc = _find_doc_record(doc_id, access.workspace_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    if req.category:
        cat = req.category.upper().strip()
        if cat in VALID_SALES_CATEGORIES:
            doc["category"] = cat
    if req.target_competitor is not None:
        doc["target_competitor"] = req.target_competitor.strip() if req.target_competitor.strip() else None
    if req.target_industry is not None:
        doc["target_industry"] = req.target_industry.strip() if req.target_industry.strip() else None
    if req.sales_summary is not None:
        doc["sales_summary"] = req.sales_summary.strip()
    if req.sales_tags is not None:
        doc["sales_tags"] = [str(t).strip() for t in req.sales_tags if str(t).strip()][:8]

    doc["classifier_used"] = "manual_user_override"
    doc["confidence_score"] = 1.0
    doc["last_updated"] = datetime.now(timezone.utc).isoformat()
    if "metadata" not in doc:
        doc["metadata"] = {}
    doc["metadata"]["sales_classification"] = {
        "category": doc.get("category"),
        "target_competitor": doc.get("target_competitor"),
        "target_industry": doc.get("target_industry"),
        "sales_summary": doc.get("sales_summary"),
        "sales_tags": doc.get("sales_tags", []),
        "classifier_used": "manual_user_override",
        "confidence_score": 1.0,
    }
    _save_doc_record(doc)

    return {
        "status": "success",
        "message": f"Updated sales classification for '{doc.get('name', doc_id)}'.",
        "document": doc,
    }


@router.post("/knowledge-vault/documents/{doc_id}/reclassify")
def reclassify_document(
    doc_id: str,
    access: WorkspaceAccess = Depends(require_workspace_member),
):
    """Re-runs the SalesClassifier (OpenRouter AI + heuristics) on an existing document."""
    require_writer(access)
    doc = _find_doc_record(doc_id, access.workspace_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Reclassify against the FULL document text (the classifier samples it within a
    # token budget), not the tiny stored preview snippet. Fall back to the snippet
    # only if the full text isn't available (e.g. not yet indexed).
    full_text = raw_document_store.get_full_text(doc_id) or doc.get("metadata", {}).get("preview_snippet", doc.get("name", ""))
    classification = sales_classifier.classify(
        filename=doc.get("name", ""),
        mime_type=doc.get("metadata", {}).get("content_type", "text/plain"),
        text_content=full_text,
    )

    doc["category"] = classification.category
    doc["target_competitor"] = classification.target_competitor
    doc["target_industry"] = classification.target_industry
    doc["sales_summary"] = classification.sales_summary
    doc["sales_tags"] = classification.sales_tags
    doc["classifier_used"] = classification.classifier_used
    doc["confidence_score"] = classification.confidence_score
    doc["last_updated"] = datetime.now(timezone.utc).isoformat()
    if "metadata" not in doc:
        doc["metadata"] = {}
    doc["metadata"]["sales_classification"] = classification.to_dict()
    _save_doc_record(doc)

    return {
        "status": "success",
        "message": f"Document re-classified as {classification.category} via {classification.classifier_used}.",
        "document": doc,
    }


@router.get("/knowledge-vault/documents/{doc_id}/vectors")
def get_document_vectors(doc_id: str, access: WorkspaceAccess = Depends(require_workspace_member)):
    """Retrieves all vector chunks, token counts, and linked list pointers for a specific document."""
    doc = _find_doc_record(doc_id, access.workspace_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    chunks = []
    # 1. Look in VectorStore in-memory
    for vid, rec in vector_store._in_memory.items():
        if rec.doc_id == doc_id or rec.doc_id.endswith(doc_id) or getattr(rec, "doc_ref_id", "") == doc_id:
            chunks.append({
                "chunk_id": rec.vector_id,
                "chunk_index": rec.chunk_index,
                "doc_ref_id": getattr(rec, "doc_ref_id", doc_id) or doc_id,
                "prev_chunk_id": getattr(rec, "prev_chunk_id", None),
                "next_chunk_id": getattr(rec, "next_chunk_id", None),
                "total_chunks": getattr(rec, "total_chunks", 0),
                "text": rec.text,
                "token_count": rec.metadata.get("token_count", len(rec.text.split())),
                "dimension": len(rec.vector),
                "metadata": rec.metadata,
                "created_at": rec.updated_at.isoformat() if hasattr(rec.updated_at, "isoformat") else str(rec.updated_at),
            })

    # 2. pgvector is the chunk store for anything indexed since the HNSW index
    # landed; MongoDB below only still holds chunks written before that.
    if not chunks and pgvector_index is not None:
        for row in pgvector_index.list_chunks(doc_id) or []:
            meta = dict(row.get("meta") or {})
            updated = row.get("updated_at")
            text_value = row.get("text", "") or ""
            chunks.append({
                "chunk_id": row.get("vector_id", ""),
                "chunk_index": row.get("chunk_index", 0),
                "doc_ref_id": row.get("doc_ref_id") or row.get("external_id") or doc_id,
                "prev_chunk_id": row.get("prev_chunk_id"),
                "next_chunk_id": row.get("next_chunk_id"),
                "total_chunks": row.get("total_chunks", 0),
                "text": text_value,
                "token_count": meta.get("token_count", len(text_value.split())),
                "dimension": row.get("dimension") or 0,
                "metadata": meta,
                "created_at": updated.isoformat() if hasattr(updated, "isoformat") else str(updated or ""),
            })

    # 3. Legacy MongoDB vector_chunks
    if not chunks and vector_store._collection is not None:
        try:
            cursor = vector_store._collection.find({
                "$or": [
                    {"doc_id": doc_id},
                    {"doc_id": {"$regex": re.escape(doc_id) + "$"}},
                    {"doc_ref_id": doc_id},
                    {"external_id": doc_id},
                    {"vector_id": {"$regex": re.escape(doc_id)}},
                ]
            }).sort("chunk_index", 1)
            for c in cursor:
                meta = c.get("metadata", {})
                chunks.append({
                    "chunk_id": c.get("vector_id", ""),
                    "chunk_index": c.get("chunk_index", 0),
                    "doc_ref_id": c.get("doc_ref_id", c.get("external_id", doc_id)),
                    "prev_chunk_id": c.get("prev_chunk_id", meta.get("prev_chunk_id")),
                    "next_chunk_id": c.get("next_chunk_id", meta.get("next_chunk_id")),
                    "total_chunks": c.get("total_chunks", meta.get("total_chunks", 0)),
                    "text": c.get("text", ""),
                    "token_count": meta.get("token_count", len(c.get("text", "").split())),
                    "dimension": len(c.get("vector", [])),
                    "metadata": meta,
                    "created_at": c.get("updated_at", ""),
                })
        except Exception as e:
            print(f"[KnowledgeVault] Vector lookup error in Mongo: {e}")

    chunks.sort(key=lambda x: x["chunk_index"])

    return {
        "status": "success",
        "doc_id": doc_id,
        "doc_ref_id": doc.get("doc_ref_id", doc_id),
        "name": doc.get("name", ""),
        "type": doc.get("type", ""),
        "category": doc.get("category", "GENERAL_RESOURCE"),
        "total_chunks": len(chunks),
        "embedding_model": doc.get("metadata", {}).get("embedding_model", "RoleSync Vector Engine (1536-dim)"),
        "chunks": chunks,
    }


@router.get("/knowledge-vault/documents/{doc_id}/content")
def get_document_content(doc_id: str, access: WorkspaceAccess = Depends(require_workspace_member)):
    """Returns the complete unfragmented markdown/text content of the document."""
    doc = _find_doc_record(doc_id, access.workspace_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    full_text = raw_document_store.get_full_text(doc_id)
    if not full_text:
        # Fallback to preview snippet if raw document not yet indexed
        full_text = doc.get("metadata", {}).get("preview_snippet", "")

    return {
        "status": "success",
        "doc_id": doc_id,
        "doc_ref_id": doc.get("doc_ref_id", doc_id),
        "filename": doc.get("name", ""),
        "category": doc.get("category", "GENERAL_RESOURCE"),
        "full_text": full_text,
        "word_count": len(full_text.split()) if full_text else 0,
        "character_count": len(full_text) if full_text else 0,
    }


@router.get("/knowledge-vault/documents/{doc_id}/download")
def download_raw_document(doc_id: str, access: WorkspaceAccess = Depends(require_workspace_member)):
    """Streams and downloads the original raw file from storage."""
    # Workspace check FIRST — raw files are keyed by doc_id only, so
    # without this a caller could download another workspace's file by id.
    doc = _find_doc_record(doc_id, access.workspace_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    raw_info = raw_document_store.get_raw_file_bytes(doc_id)
    if not raw_info:
        text = doc.get("metadata", {}).get("preview_snippet", "")
        return Response(
            content=text.encode("utf-8"),
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename=\"{doc.get('name', 'document.txt')}\""},
        )

    content_bytes, filename, mime_type = raw_info
    return Response(
        content=content_bytes,
        media_type=mime_type,
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
    )


@router.delete("/knowledge-vault/documents/{doc_id}")
def delete_document(doc_id: str, access: WorkspaceAccess = Depends(require_workspace_member)):
    """Deletes a document and purges all its vector embeddings and raw files (uploader or workspace owner/admin)."""
    doc = _find_doc_record(doc_id, access.workspace_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    require_writer(access)
    if doc.get("user_id") != access.user_id and not access.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Only the person who added this document or a workspace owner/admin can delete it.",
        )

    _delete_doc_record(doc_id)
    raw_document_store.delete_raw_document(doc_id)
    return {
        "status": "success",
        "message": f"Document '{doc.get('name', doc_id)}' and its vector chunks were purged successfully.",
        "doc_id": doc_id,
    }


@router.post("/knowledge-vault/documents/{doc_id}/reindex")
def reindex_document(
    doc_id: str,
    background_tasks: BackgroundTasks,
    access: WorkspaceAccess = Depends(require_workspace_member),
):
    """Re-triggers chunking and vector indexing using the stored complete document."""
    require_writer(access)
    doc = _find_doc_record(doc_id, access.workspace_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Remove old vectors
    vector_store.delete_by_doc_id(doc_id)

    # Set status to Parsing
    doc["status"] = "Parsing"
    doc["chunks"] = 0
    doc["last_updated"] = datetime.now(timezone.utc).isoformat()
    _save_doc_record(doc)

    # 1. Attempt to pull original file bytes or full text from raw_document_store
    raw_tuple = raw_document_store.get_raw_file_bytes(doc_id)
    if raw_tuple:
        content_bytes, filename, mime_type = raw_tuple
    else:
        full_text = raw_document_store.get_full_text(doc_id)
        if full_text:
            content_bytes = full_text.encode("utf-8", errors="replace")
            filename = doc.get("name", f"{doc_id}.md")
            mime_type = "text/markdown"
        else:
            snippet = doc.get("metadata", {}).get("preview_snippet", doc.get("name", ""))
            content_bytes = snippet.encode("utf-8", errors="replace")
            filename = doc.get("name", "")
            mime_type = "text/plain"

    _queue_document_job(
        background_tasks,
        doc_id=doc_id,
        tenant_id=access.workspace_id,
        user_id=doc.get("user_id") or access.user_id,
        raw_bytes=content_bytes,
        filename=filename,
        mime_type=mime_type,
        source=doc.get("source", "USER_UPLOAD"),
        user_override_category=doc.get("category"),
        user_override_competitor=doc.get("target_competitor"),
    )

    return {
        "status": "success",
        "message": f"Document '{filename}' queued for full re-indexing with complete unfragmented content.",
        "document": doc,
    }


@router.post("/knowledge-vault/backfill-chunks")
def backfill_existing_chunks(access: WorkspaceAccess = Depends(require_workspace_member)):
    """
    Backfills the workspace's MongoDB vector_chunks with doc_ref_id, prev_chunk_id, next_chunk_id,
    and category metadata from parent knowledge_documents (workspace owners/admins only).
    """
    if not access.is_admin:
        raise HTTPException(status_code=403, detail="Only a workspace owner/admin can backfill chunks.")
    if vector_store._collection is None:
        return {"status": "skipped", "message": "MongoDB offline."}

    updated_count = 0
    try:
        # Group chunks by doc_id / external_id
        cursor = vector_store._collection.find({}).sort([("doc_id", 1), ("chunk_index", 1)])
        doc_chunks_map: dict[str, list[dict[str, Any]]] = {}
        for c in cursor:
            parent_id = c.get("external_id") or c.get("doc_id", "")
            if not parent_id:
                continue
            doc_chunks_map.setdefault(parent_id, []).append(c)

        for parent_id, chunk_list in list(doc_chunks_map.items()):
            # Only this workspace's documents; other workspaces' chunks are left untouched.
            parent_doc = _find_doc_record(parent_id, access.workspace_id)
            if parent_doc is None:
                doc_chunks_map.pop(parent_id)
                continue
            total = len(chunk_list)
            category = parent_doc.get("category", "GENERAL_RESOURCE") if parent_doc else "GENERAL_RESOURCE"
            competitor = parent_doc.get("target_competitor") if parent_doc else None

            for idx, ch in enumerate(chunk_list):
                prev_id = chunk_list[idx - 1].get("vector_id") if idx > 0 else None
                next_id = chunk_list[idx + 1].get("vector_id") if idx < total - 1 else None
                meta = ch.get("metadata", {})
                meta["doc_ref_id"] = parent_id
                meta["parent_doc_id"] = parent_id
                meta["category"] = meta.get("category") or category
                meta["document_type"] = meta.get("document_type") or category
                meta["prev_chunk_id"] = prev_id
                meta["next_chunk_id"] = next_id
                meta["chunk_index"] = idx
                meta["total_chunks"] = total
                if competitor:
                    meta["target_competitor"] = competitor

                vector_store._collection.update_one(
                    {"_id": ch["_id"]},
                    {"$set": {
                        "doc_ref_id": parent_id,
                        "prev_chunk_id": prev_id,
                        "next_chunk_id": next_id,
                        "total_chunks": total,
                        "metadata": meta,
                    }}
                )
                updated_count += 1

        print(f"[KnowledgeVault] Successfully backfilled {updated_count} vector chunks across {len(doc_chunks_map)} documents.")
    except Exception as e:
        print(f"[KnowledgeVault] Backfill error: {e}")
        return {"status": "error", "error": str(e)}

    return {
        "status": "success",
        "updated_chunks": updated_count,
        "total_documents": len(doc_chunks_map),
    }


@router.post("/knowledge-vault/deduplicate")
def deduplicate_documents(
    confirm: bool = False,
    access: WorkspaceAccess = Depends(require_workspace_member),
):
    """Finds duplicate documents in the workspace — same content hash, or same
    name+size+type for legacy rows uploaded before hashing — and, on ``confirm=true``,
    removes every copy except the best one (most chunks / newest indexed).

    Defaults to a dry run so the caller can preview exactly what would be removed. The
    destructive pass requires a workspace owner/admin because it can delete documents
    uploaded by other members.
    """
    require_writer(access)
    if confirm and not access.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Only a workspace owner/admin can remove duplicate documents.",
        )

    docs = _list_doc_records(access.workspace_id)
    plan = plan_deduplication(docs)

    removed: list[str] = []
    if confirm:
        for group in plan:
            for loser in group["removed"]:
                did = loser.get("doc_id")
                if not did:
                    continue
                _delete_doc_record(did)
                raw_document_store.delete_raw_document(did)
                removed.append(did)

    removable = sum(len(g["removed"]) for g in plan)
    return {
        "status": "success",
        "dry_run": not confirm,
        "duplicate_groups": len(plan),
        "removable_documents": removable,
        "removed_documents": len(removed),
        "details": plan,
        "message": (
            f"Removed {len(removed)} duplicate document(s); kept {len(plan)} original(s)."
            if confirm
            else (
                f"Found {removable} duplicate document(s) across {len(plan)} group(s). "
                "Re-run with confirm=true to remove them."
                if removable
                else "No duplicate documents found — your vault is clean."
            )
        ),
    }


class VaultSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=50)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)


@router.post("/knowledge-vault/search")
def search_knowledge_vault(
    req: VaultSearchRequest,
    access: WorkspaceAccess = Depends(require_workspace_member),
):
    """Semantic search across indexed chunks.

    Embeds the query (RETRIEVAL_QUERY) and runs an ANN lookup against the HNSW
    index, with the workspace and the caller's ACL applied as filters.
    """
    query_vector = query_embedder.embed_query(req.query)
    if query_vector is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Semantic search is temporarily unavailable. Please try again, "
                "or use keyword filters in the meantime."
            ),
        )

    # Chunks are tagged with the owning user and the workspace they belong to.
    user_acl = [f"tenant:{access.workspace_id}", f"user:{access.user_id}", access.user_id]

    try:
        matches = vector_store.search_similarity(
            query_vector=query_vector,
            tenant_id=access.workspace_id,
            user_acl=user_acl,
            limit=req.limit,
            min_score=req.min_score,
        )
    except Exception as err:
        print(f"[KnowledgeVault] Semantic search failed: {err}")
        raise HTTPException(status_code=503, detail="Search failed. Please try again.")

    return {
        "status": "success",
        "query": req.query,
        "count": len(matches),
        "results": [
            {
                "chunk_id": rec.vector_id,
                "doc_id": rec.doc_id,
                "doc_ref_id": rec.doc_ref_id or rec.external_id,
                "chunk_index": rec.chunk_index,
                "text": rec.text,
                "score": rec.metadata.get("similarity_score"),
                "category": rec.metadata.get("category"),
                "document_type": rec.metadata.get("document_type"),
            }
            for rec in matches
        ],
    }


@router.get("/knowledge-vault/config")
def get_rag_config_endpoint(access: WorkspaceAccess = Depends(require_workspace_member)):
    """Returns the caller's RAG parameters in this workspace."""
    cfg = _get_rag_config(access.workspace_id, access.user_id)
    return {"status": "success", "config": cfg}


@router.post("/knowledge-vault/config")
def save_rag_config_endpoint(req: RagConfigRequest, access: WorkspaceAccess = Depends(require_workspace_member)):
    """Saves and updates the caller's RAG parameters in this workspace."""
    require_writer(access)
    data = {
        "chunk_size": req.chunk_size,
        "overlap": req.overlap,
        "embedding_engine": req.embedding_engine,
        "similarity_threshold": req.similarity_threshold if req.similarity_threshold is not None else 0.72,
    }
    _save_rag_config(access.workspace_id, access.user_id, data)
    return {
        "status": "success",
        "message": "RAG configuration updated successfully.",
        "config": _get_rag_config(access.workspace_id, access.user_id),
    }
