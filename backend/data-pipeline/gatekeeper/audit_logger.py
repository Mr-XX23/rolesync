from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

@dataclass
class AuditLogEntry:
    doc_id: str
    tenant_id: str
    user_id: str
    source: str
    category: str
    decision: str  # ACCEPTED, REJECTED_LEXICAL, QUARANTINED
    reason: str
    entropy: float
    policy_version: str = "v1.0.0"
    logged_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class GatekeeperAuditLogger:
    """Audit logger capturing every memory gatekeeper decision and policy version."""

    def __init__(self) -> None:
        self._logs: list[AuditLogEntry] = []

    def log_decision(
        self,
        doc_id: str,
        tenant_id: str,
        user_id: str,
        source: str,
        category: str,
        decision: str,
        reason: str,
        entropy: float = 0.0,
        policy_version: str = "v1.0.0",
    ) -> AuditLogEntry:
        entry = AuditLogEntry(
            doc_id=doc_id,
            tenant_id=tenant_id,
            user_id=user_id,
            source=source,
            category=category,
            decision=decision,
            reason=reason,
            entropy=entropy,
            policy_version=policy_version,
        )
        self._logs.append(entry)
        print(f"[GatekeeperAuditLogger] Logged decision for doc_id={doc_id}: decision={decision}, category={category}, reason='{reason}'")
        return entry

    def get_logs_for_doc(self, doc_id: str) -> list[AuditLogEntry]:
        return [entry for entry in self._logs if entry.doc_id == doc_id]
