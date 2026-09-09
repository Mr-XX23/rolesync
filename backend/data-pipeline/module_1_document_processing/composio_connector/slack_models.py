from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

class SlackSyncStatus(str, Enum):
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

class SlackTriggerType(str, Enum):
    INITIAL_SYNC = "INITIAL_SYNC"
    AUTO_SYNC = "AUTO_SYNC"
    MANUAL_SYNC = "MANUAL_SYNC"
    RESYNC = "RESYNC"
    WEBHOOK = "WEBHOOK"

class HistoricalSyncStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"

@dataclass
class SlackSyncConfig:
    max_messages_per_sync: int = 15        # 1 to 30 (default: 15)
    categories: list[str] = field(default_factory=lambda: ["PUBLIC_CHANNELS", "DIRECT_MESSAGES", "GROUP_MESSAGES"])
    sync_window_days: int = 180            # default: 180 days
    auto_sync_interval_minutes: int = 0    # default: 0 (OFF by default)
    sync_frequency: str = "off"            # "off", 2m, 30m, 1h, 6h, 24h
    auto_sync_enabled: bool = False        # default: False (OFF)
    webhook_enabled: bool = False          # default: False (OFF)

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_messages_per_sync": self.max_messages_per_sync,
            "categories": self.categories,
            "sync_window_days": self.sync_window_days,
            "auto_sync_interval_minutes": self.auto_sync_interval_minutes,
            "sync_frequency": self.sync_frequency,
            "auto_sync_enabled": self.auto_sync_enabled,
            "webhook_enabled": self.webhook_enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SlackSyncConfig":
        freq = str(data.get("sync_frequency", "off"))
        auto_enabled = bool(data.get("auto_sync_enabled", False if freq == "off" else True))
        cats = list(data.get("categories") or ["PUBLIC_CHANNELS", "DIRECT_MESSAGES", "GROUP_MESSAGES"])
        return cls(
            max_messages_per_sync=max(1, min(30, int(data.get("max_messages_per_sync", data.get("max_items_per_sync", 15))))),
            categories=cats,
            sync_window_days=int(data.get("sync_window_days", 180)),
            auto_sync_interval_minutes=int(data.get("auto_sync_interval_minutes", 0)),
            sync_frequency=freq,
            auto_sync_enabled=auto_enabled,
            webhook_enabled=bool(data.get("webhook_enabled", False)),
        )

@dataclass
class SlackBackfillState:
    historical_sync_status: HistoricalSyncStatus = HistoricalSyncStatus.NOT_STARTED
    historical_sync_cursor: str | None = None
    historical_sync_boundary: str | None = None
    is_backfill_complete: bool = False
    oldest_synced_timestamp: str | None = None
    newest_synced_timestamp: str | None = None
    next_page_token: str | None = None
    total_eligible_discovered: int = 0
    total_synced_so_far: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "historical_sync_status": self.historical_sync_status.value if isinstance(self.historical_sync_status, HistoricalSyncStatus) else str(self.historical_sync_status),
            "historical_sync_cursor": self.historical_sync_cursor or self.next_page_token,
            "historical_sync_boundary": self.historical_sync_boundary,
            "is_backfill_complete": self.is_backfill_complete or (self.historical_sync_status == HistoricalSyncStatus.COMPLETED),
            "oldest_synced_timestamp": self.oldest_synced_timestamp,
            "newest_synced_timestamp": self.newest_synced_timestamp,
            "next_page_token": self.next_page_token or self.historical_sync_cursor,
            "total_eligible_discovered": self.total_eligible_discovered,
            "total_synced_so_far": self.total_synced_so_far,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SlackBackfillState":
        raw_status = data.get("historical_sync_status")
        if raw_status:
            try:
                hist_status = HistoricalSyncStatus(raw_status)
            except Exception:
                hist_status = HistoricalSyncStatus.NOT_STARTED
        else:
            hist_status = HistoricalSyncStatus.COMPLETED if data.get("is_backfill_complete") else HistoricalSyncStatus.NOT_STARTED

        cursor = data.get("historical_sync_cursor") or data.get("next_page_token")
        return cls(
            historical_sync_status=hist_status,
            historical_sync_cursor=cursor,
            historical_sync_boundary=data.get("historical_sync_boundary"),
            is_backfill_complete=bool(data.get("is_backfill_complete", hist_status == HistoricalSyncStatus.COMPLETED)),
            oldest_synced_timestamp=data.get("oldest_synced_timestamp"),
            newest_synced_timestamp=data.get("newest_synced_timestamp"),
            next_page_token=cursor,
            total_eligible_discovered=int(data.get("total_eligible_discovered", 0)),
            total_synced_so_far=int(data.get("total_synced_so_far", 0)),
        )

@dataclass
class SlackLockState:
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
    def from_dict(cls, data: dict[str, Any]) -> "SlackLockState":
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
class SlackConnection:
    connection_id: str
    tenant_id: str
    user_id: str
    account_name: str = ""
    status: SlackSyncStatus = SlackSyncStatus.AVAILABLE
    config: SlackSyncConfig = field(default_factory=SlackSyncConfig)
    backfill_state: SlackBackfillState = field(default_factory=SlackBackfillState)
    lock: SlackLockState = field(default_factory=SlackLockState)
    current_progress: str = ""  # e.g. "3 of 15"
    webhook_trigger_id: str | None = None
    last_successful_sync_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "account_name": self.account_name,
            "status": self.status.value if isinstance(self.status, SlackSyncStatus) else str(self.status),
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
class SyncedSlackMessageRecord:
    doc_id: str
    tenant_id: str
    connection_id: str
    message_id: str          # f"{channel_id}:{message_ts}"
    channel_id: str
    channel_name: str
    message_type: str        # "public_channel", "private_channel", "im", "mpim"
    sender_id: str
    sender_name: str
    text: str
    thread_ts: str | None = None
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sync_status: str = "SUCCESS"  # SUCCESS, PARTIAL_SUCCESS, FAILED, SKIPPED
    attachments: list[dict[str, Any]] = field(default_factory=list)
    vector_chunk_count: int = 0
    synced_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        rec_str = self.received_at.isoformat() if hasattr(self.received_at, "isoformat") else str(self.received_at)
        syn_str = self.synced_at.isoformat() if hasattr(self.synced_at, "isoformat") else str(self.synced_at)
        return {
            "doc_id": self.doc_id,
            "tenant_id": self.tenant_id,
            "connection_id": self.connection_id,
            "message_id": self.message_id,
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "message_type": self.message_type,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "text": self.text,
            "thread_ts": self.thread_ts,
            "received_at": rec_str,
            "sync_status": self.sync_status,
            "attachments": self.attachments,
            "vector_chunk_count": self.vector_chunk_count,
            "synced_at": syn_str,
        }

@dataclass
class SlackActivityItem:
    message_id: str
    channel_id: str
    channel_name: str
    sender_name: str
    text_snippet: str
    message_type: str
    status: str  # SUCCESS, PARTIAL_SUCCESS, SKIPPED, FAILED
    error_message: str | None = None
    thread_ts: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "sender_name": self.sender_name,
            "name": f"#{self.channel_name}: {self.text_snippet[:60]}",
            "subject": f"#{self.channel_name} - {self.sender_name}",
            "sender": self.sender_name,
            "message_type": self.message_type,
            "status": self.status,
            "error_message": self.error_message,
            "thread_ts": self.thread_ts,
        }

@dataclass
class SlackSyncActivity:
    activity_id: str
    job_id: str
    connection_id: str
    tenant_id: str
    trigger_type: SlackTriggerType
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
            "trigger_type": self.trigger_type.value if isinstance(self.trigger_type, SlackTriggerType) else str(self.trigger_type),
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metrics": self.metrics,
            "items": self.items,
        }
