from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

@dataclass
class ParseFailureRecord:
    doc_id: str
    tenant_id: str
    user_id: str
    source: str
    external_id: str
    reason: str
    mime_type: str
    failed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class ParseFailureStore:
    """Parse failure store capturing parsing errors, unsupported MIME types, and corrupt payloads."""

    def __init__(self) -> None:
        self._failures: dict[str, ParseFailureRecord] = {}

    def record_failure(
        self,
        doc_id: str,
        tenant_id: str,
        user_id: str,
        source: str,
        external_id: str,
        reason: str,
        mime_type: str = "",
    ) -> ParseFailureRecord:
        record = ParseFailureRecord(
            doc_id=doc_id,
            tenant_id=tenant_id,
            user_id=user_id,
            source=source,
            external_id=external_id,
            reason=reason,
            mime_type=mime_type,
        )
        self._failures[doc_id] = record
        print(f"[ParseFailureStore] Recorded parse failure for doc_id={doc_id}: {reason}")
        return record

    def get_failure(self, doc_id: str) -> ParseFailureRecord | None:
        return self._failures.get(doc_id)
