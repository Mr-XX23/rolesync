"""Normalized document text, stored in Postgres.

Every ingestion path writes the parsed text here, so a document can be
re-indexed, re-classified or displayed **without re-fetching it from the
provider** - which for connector documents (Gmail, Drive, Slack, Notion,
Calendar) would otherwise cost billable Composio executions every time.

MongoDB remains a read fallback for documents ingested before this existed.
"""
from __future__ import annotations

from typing import Optional

try:
    from sqlalchemy import delete, select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from rag.database import session_scope
    from rag.models import DocumentContent
    from rag.state import persistence_available

    _RAG_AVAILABLE = True
except Exception:  # pragma: no cover - sqlalchemy / rag package unavailable
    _RAG_AVAILABLE = False


class DocumentContentStore:
    """Read/write the parsed text of a document."""

    def available(self) -> bool:
        return _RAG_AVAILABLE and persistence_available()

    def save(
        self,
        doc_id: str,
        full_text: str,
        tenant_id: str = "",
        source: str = "",
        parser_used: str = "",
    ) -> bool:
        """Upsert the document text. False means the caller should fall back."""
        if not self.available() or not doc_id or not full_text:
            return False

        try:
            with session_scope() as session:
                statement = pg_insert(DocumentContent).values(
                    doc_id=doc_id,
                    tenant_id=tenant_id or "",
                    source=(source or "").lower(),
                    full_text=full_text,
                    parser_used=parser_used or "",
                    char_count=len(full_text),
                    word_count=len(full_text.split()),
                )
                session.execute(
                    statement.on_conflict_do_update(
                        index_elements=["doc_id"],
                        set_={
                            "full_text": statement.excluded.full_text,
                            "tenant_id": statement.excluded.tenant_id,
                            "source": statement.excluded.source,
                            "parser_used": statement.excluded.parser_used,
                            "char_count": statement.excluded.char_count,
                            "word_count": statement.excluded.word_count,
                        },
                    )
                )
            return True
        except Exception as err:
            print(f"[DocumentContentStore] Save failed for {doc_id}: {err}")
            return False

    def get(self, doc_id: str) -> Optional[str]:
        if not self.available() or not doc_id:
            return None
        try:
            with session_scope() as session:
                return session.execute(
                    select(DocumentContent.full_text).where(DocumentContent.doc_id == doc_id)
                ).scalar_one_or_none()
        except Exception as err:
            print(f"[DocumentContentStore] Read failed for {doc_id}: {err}")
            return None

    def delete(self, doc_id: str) -> bool:
        if not self.available() or not doc_id:
            return False
        try:
            with session_scope() as session:
                session.execute(delete(DocumentContent).where(DocumentContent.doc_id == doc_id))
            return True
        except Exception as err:
            print(f"[DocumentContentStore] Delete failed for {doc_id}: {err}")
            return False


document_content_store = DocumentContentStore()
