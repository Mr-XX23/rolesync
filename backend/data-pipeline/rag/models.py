"""SQLAlchemy models backing the RAG ingestion pipeline's durable state.

rag.documents        - Canonical DB: one row per ingested document (status, ACL snapshot, lineage counters)
rag.document_events  - Append-only lineage of every pipeline stage transition
rag.chunk_hashes     - Versioned Hash DB: chunk fingerprints powering delta de-duplication
rag.checkpoints      - Batch ingestion checkpoints enabling resume after a restart
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from rag.database import RAG_SCHEMA, Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RagDocument(Base):
    """Canonical record: the pipeline's source of truth for a document's lifecycle."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_rag_documents_tenant_source", "tenant_id", "source"),
        Index("ix_rag_documents_tenant_user", "tenant_id", "user_id"),
        {"schema": RAG_SCHEMA},
    )

    doc_id = Column(String(512), primary_key=True)
    tenant_id = Column(String(128), nullable=False, default="")
    user_id = Column(String(128), nullable=False, default="")
    source = Column(String(64), nullable=False, default="")
    external_id = Column(String(512), nullable=False, default="")
    status = Column(String(64), nullable=False, default="STAGED")
    acl = Column(JSONB, nullable=False, default=list)
    event_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class DocumentEvent(Base):
    """Append-only lineage: every stage transition a document passed through."""

    __tablename__ = "document_events"
    __table_args__ = (
        Index("ix_rag_document_events_doc", "doc_id", "created_at"),
        {"schema": RAG_SCHEMA},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    doc_id = Column(String(512), nullable=False)
    event_id = Column(String(128), nullable=False, default="")
    event_type = Column(String(64), nullable=False, default="")
    status = Column(String(64), nullable=False, default="")
    payload = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class DocumentContent(Base):
    """The normalized (parsed) text of a document.

    Kept in Postgres rather than MongoDB for three reasons: a BSON document is
    capped at 16MB and a large parsed PDF can approach it; the text then lives in
    the same database as the chunks and lineage, so a write is one transaction and
    an erasure is one cascade; and it leaves room for a tsvector column to add
    keyword/hybrid search alongside the vector index.

    Deliberately a separate table from `documents`: the reconciliation sweeper
    scans that one, and should not drag document bodies along with it.
    """

    __tablename__ = "document_content"
    __table_args__ = (
        Index("ix_rag_document_content_tenant", "tenant_id", "source"),
        {"schema": RAG_SCHEMA},
    )

    doc_id = Column(String(512), primary_key=True)
    tenant_id = Column(String(128), nullable=False, default="")
    source = Column(String(64), nullable=False, default="")
    full_text = Column(Text, nullable=False, default="")
    parser_used = Column(String(64), nullable=False, default="")
    char_count = Column(Integer, nullable=False, default=0)
    word_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class ChunkHash(Base):
    """Chunk fingerprint enabling cross-run delta de-duplication."""

    __tablename__ = "chunk_hashes"
    __table_args__ = ({"schema": RAG_SCHEMA},)

    doc_id = Column(String(512), primary_key=True)
    chunk_id = Column(String(512), primary_key=True)
    chunk_hash = Column(String(128), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class Checkpoint(Base):
    """Batch ingestion checkpoint (PENDING / PROCESSING / DONE / FAILED)."""

    __tablename__ = "checkpoints"
    __table_args__ = (
        Index("ix_rag_checkpoints_doc", "doc_id"),
        Index("ix_rag_checkpoints_tenant_status", "tenant_id", "status"),
        {"schema": RAG_SCHEMA},
    )

    batch_id = Column(String(512), primary_key=True)
    doc_id = Column(String(512), nullable=False, default="")
    tenant_id = Column(String(128), nullable=False, default="")
    status = Column(String(32), nullable=False, default="PENDING")
    chunks_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
