from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent

@dataclass
class StagedDocument:
    doc_id: str
    tenant_id: str
    user_id: str
    source: str
    external_id: str
    status: str  # STAGED, PARSED_SUCCESS, PARSED_FAILED, GATEKEEPER_ACCEPTED, GATEKEEPER_REJECTED, VECTOR_STORE_INDEXED, DELETED
    event_history: list[CanonicalEvent] = field(default_factory=list)
    acl: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class CanonicalStore:
    """Canonical Store tracking raw lineage, ACL snapshots, and document lifecycle status."""

    def __init__(self) -> None:
        self._store: dict[str, StagedDocument] = {}

    def record_event(self, event: CanonicalEvent, status: str = "STAGED") -> StagedDocument:
        doc_id = f"{event.tenant_id}:{event.source}:{event.external_id}"
        staged = self._store.get(doc_id)

        if staged is None:
            staged = StagedDocument(
                doc_id=doc_id,
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                source=event.source,
                external_id=event.external_id,
                status=status,
                acl=list(event.acl),
            )
            self._store[doc_id] = staged
        else:
            staged.status = status
            staged.acl = list(event.acl)
            staged.updated_at = datetime.now(timezone.utc)

        staged.event_history.append(event)
        print(f"[CanonicalStore] Recorded event lineage for doc_id={doc_id}, status={status}")
        return staged

    def get_document(self, doc_id: str) -> StagedDocument | None:
        return self._store.get(doc_id)

    def update_acl(self, doc_id: str, new_acl: list[str]) -> bool:
        staged = self._store.get(doc_id)
        if staged:
            staged.acl = list(new_acl)
            staged.updated_at = datetime.now(timezone.utc)
            print(f"[CanonicalStore] Updated ACL snapshot for doc_id={doc_id}: {new_acl}")
            return True
        return False

    def purge_by_tenant_source_user(self, tenant_id: str, source: str, user_id: str = "") -> int:
        to_delete = [
            doc_id for doc_id, doc in self._store.items()
            if doc.tenant_id == tenant_id and doc.source.lower() == source.lower() and (not user_id or doc.user_id == user_id)
        ]
        for doc_id in to_delete:
            self._store.pop(doc_id, None)
        print(f"[CanonicalStore] Purged {len(to_delete)} staged docs for tenant={tenant_id}, source={source}, user={user_id}.")
        return len(to_delete)
