from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

class GmailSyncStatus(str, Enum):
    AVAILABLE = "Available"
    CONFIGURATION_REQUIRED = "Configuration Required"
    CONNECTED = "Connected"
    SYNCING = "Syncing"
    WAITING_FOR_NEXT_AUTO_SYNC = "Waiting for Next Auto Sync"
    UP_TO_DATE = "Up to Date"
    PARTIAL_SUCCESS = "Partial Success"
    FAILED = "Failed"
    PAUSED = "Paused"
    DISCONNECTED = "Disconnected"

class GmailTriggerType(str, Enum):
    INITIAL_SYNC = "INITIAL_SYNC"
    AUTO_SYNC = "AUTO_SYNC"
    MANUAL_SYNC = "MANUAL_SYNC"
    RESYNC = "RESYNC"
    WEBHOOK = "WEBHOOK"

@dataclass
class GmailSyncConfig:
    max_emails_per_sync: int = 10           # 1 to 30 (default: 10)
    categories: list[str] = field(default_factory=lambda: ["INBOX"]) # INBOX, SENT, PROMOTIONS, SOCIAL, ALL
    sync_window_days: int = 90             # default: 90 days
    auto_sync_interval_minutes: int = 30   # default: 30 minutes
    max_attachment_size_mb: int = 25       # default: 25 MB

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_emails_per_sync": self.max_emails_per_sync,
            "categories": self.categories,
            "sync_window_days": self.sync_window_days,
            "auto_sync_interval_minutes": self.auto_sync_interval_minutes,
            "max_attachment_size_mb": self.max_attachment_size_mb,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GmailSyncConfig":
        return cls(
            max_emails_per_sync=int(data.get("max_emails_per_sync", 10)),
            categories=list(data.get("categories", ["INBOX"])),
            sync_window_days=int(data.get("sync_window_days", 90)),
            auto_sync_interval_minutes=int(data.get("auto_sync_interval_minutes", 30)),
            max_attachment_size_mb=int(data.get("max_attachment_size_mb", 25)),
        )

@dataclass
class GmailBackfillState:
    is_backfill_complete: bool = False
    oldest_synced_timestamp: str | None = None
    next_page_token: str | None = None
    total_eligible_discovered: int = 0
    total_synced_so_far: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_backfill_complete": self.is_backfill_complete,
            "oldest_synced_timestamp": self.oldest_synced_timestamp,
            "next_page_token": self.next_page_token,
            "total_eligible_discovered": self.total_eligible_discovered,
            "total_synced_so_far": self.total_synced_so_far,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GmailBackfillState":
        return cls(
            is_backfill_complete=bool(data.get("is_backfill_complete", False)),
            oldest_synced_timestamp=data.get("oldest_synced_timestamp"),
            next_page_token=data.get("next_page_token"),
            total_eligible_discovered=int(data.get("total_eligible_discovered", 0)),
            total_synced_so_far=int(data.get("total_synced_so_far", 0)),
        )

@dataclass
class GmailLockState:
    is_locked: bool = False
    locked_by_job_id: str | None = None
    locked_at: datetime | None = None
    expires_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_locked": self.is_locked,
            "locked_by_job_id": self.locked_by_job_id,
            "locked_at": self.locked_at.isoformat() if self.locked_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GmailLockState":
        locked_at = None
        expires_at = None
        if data.get("locked_at"):
            try:
                locked_at = datetime.fromisoformat(data["locked_at"])
            except Exception:
                pass
        if data.get("expires_at"):
            try:
                expires_at = datetime.fromisoformat(data["expires_at"])
            except Exception:
                pass
        return cls(
            is_locked=bool(data.get("is_locked", False)),
            locked_by_job_id=data.get("locked_by_job_id"),
            locked_at=locked_at,
            expires_at=expires_at,
        )

@dataclass
class GmailConnection:
    connection_id: str
    tenant_id: str
    user_id: str
    account_email: str = ""
    status: GmailSyncStatus = GmailSyncStatus.AVAILABLE
    config: GmailSyncConfig = field(default_factory=GmailSyncConfig)
    backfill_state: GmailBackfillState = field(default_factory=GmailBackfillState)
    lock: GmailLockState = field(default_factory=GmailLockState)
    current_progress: str = ""  # e.g. "3 of 10"
    webhook_trigger_id: str | None = None
    last_successful_sync_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "account_email": self.account_email,
            "status": self.status.value if isinstance(self.status, GmailSyncStatus) else str(self.status),
            "config": self.config.to_dict(),
            "backfill_state": self.backfill_state.to_dict(),
            "lock": self.lock.to_dict(),
            "current_progress": self.current_progress,
            "webhook_trigger_id": self.webhook_trigger_id,
            "last_successful_sync_at": self.last_successful_sync_at.isoformat() if self.last_successful_sync_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

@dataclass
class AttachmentAuditItem:
    filename: str
    mime_type: str
    size_bytes: int
    parse_status: str  # SUCCESS, SKIPPED, FAILED
    parser: str | None = None
    skip_reason: str | None = None  # e.g. "ATTACHMENT_SIZE_EXCEEDED (>25MB)", "UNSUPPORTED_FORMAT"

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "parse_status": self.parse_status,
            "parser": self.parser,
            "skip_reason": self.skip_reason,
        }

@dataclass
class SyncedMessageRecord:
    doc_id: str
    tenant_id: str
    connection_id: str
    message_id: str
    thread_id: str
    categories: list[str]
    subject: str
    sender: str
    received_at: datetime
    sync_status: str  # SUCCESS, PARTIAL_SUCCESS, FAILED, SKIPPED
    attachments: list[dict[str, Any]] = field(default_factory=list)
    vector_chunk_count: int = 0
    synced_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "tenant_id": self.tenant_id,
            "connection_id": self.connection_id,
            "message_id": self.message_id,
            "thread_id": self.thread_id,
            "categories": self.categories,
            "subject": self.subject,
            "sender": self.sender,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "sync_status": self.sync_status,
            "attachments": self.attachments,
            "vector_chunk_count": self.vector_chunk_count,
            "synced_at": self.synced_at.isoformat(),
        }

@dataclass
class SyncActivityItem:
    message_id: str
    subject: str
    sender: str
    status: str  # SUCCESS, PARTIAL_SUCCESS, SKIPPED, FAILED
    attachment_summary: str
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "subject": self.subject,
            "sender": self.sender,
            "status": self.status,
            "attachment_summary": self.attachment_summary,
            "error_message": self.error_message,
        }

@dataclass
class GmailSyncActivity:
    activity_id: str
    job_id: str
    connection_id: str
    tenant_id: str
    trigger_type: GmailTriggerType
    status: str  # RUNNING, COMPLETED, PARTIAL_SUCCESS, FAILED
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    metrics: dict[str, int] = field(default_factory=lambda: {
        "total_discovered": 0,
        "processed": 0,
        "succeeded": 0,
        "skipped": 0,
        "failed": 0,
    })
    items: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "job_id": self.job_id,
            "connection_id": self.connection_id,
            "tenant_id": self.tenant_id,
            "trigger_type": self.trigger_type.value if isinstance(self.trigger_type, GmailTriggerType) else str(self.trigger_type),
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metrics": self.metrics,
            "items": self.items,
        }
