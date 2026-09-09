import os
import threading
from datetime import datetime, timezone, timedelta
from typing import Any
from module_1_document_processing.composio_connector.gmail_models import (
    GmailConnection,
    GmailSyncStatus,
    GmailSyncConfig,
    GmailBackfillState,
    GmailLockState,
    SyncedMessageRecord,
    GmailSyncActivity,
    GmailTriggerType,
)

try:
    from pymongo import MongoClient, ASCENDING
except ImportError:
    MongoClient = None
    ASCENDING = 1

from module_1_document_processing.composio_connector.distributed_lock import DistributedLockManager

class GmailStore:
    """MongoDB & In-Memory Store managing Gmail connections, deduplication, locks, and sync activity logs."""

    def __init__(self) -> None:
        self.mongo_uri = os.environ.get("MONGODB_URI", "mongodb://mongodb:27017")
        self.db_name = os.environ.get("MONGODB_DB_NAME", "rolesync_rag")
        # Use RLock for re-entrant thread safety
        self._lock = threading.RLock()

        # In-memory stores
        self._connections: dict[str, GmailConnection] = {}
        self._synced_messages: dict[str, SyncedMessageRecord] = {}  # key: f"{tenant_id}:{connection_id}:{message_id}"
        self._activities: dict[str, list[GmailSyncActivity]] = {}  # key: connection_id -> list

        self._mongo_client = None
        self._db = None
        self._lock_manager = DistributedLockManager(db=None)
        if MongoClient and self.mongo_uri:
            try:
                self._mongo_client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=500)
                # Verify live connection immediately with ping
                self._mongo_client.admin.command("ping")
                self._db = self._mongo_client[self.db_name]
                self._lock_manager.set_db(self._db)
                # Ensure compound unique index for deduplication
                self._db.gmail_synced_messages.create_index(
                    [("tenant_id", ASCENDING), ("connection_id", ASCENDING), ("message_id", ASCENDING)],
                    unique=True
                )
                self._db.gmail_synced_messages.create_index([("tenant_id", ASCENDING), ("connection_id", ASCENDING), ("received_at", -1)])
                self._db.gmail_connections.create_index([("tenant_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
                self._db.gmail_sync_activities.create_index([("connection_id", ASCENDING), ("started_at", -1)])
                print(f"[GmailStore] Initialized MongoDB collections and compound indexes at {self.mongo_uri}/{self.db_name}")
            except Exception as err:
                print(f"[GmailStore] Using fast in-memory store (MongoDB offline / local mode: {err})")
                self._db = None
                self._mongo_client = None
                self._lock_manager.set_db(None)

    def get_or_create_connection(self, tenant_id: str, user_id: str, account_email: str = "") -> GmailConnection:
        conn_id = f"conn_gmail_{tenant_id}_{user_id}"
        with self._lock:
            # Check MongoDB first
            if self._db is not None:
                try:
                    doc = self._db.gmail_connections.find_one({"tenant_id": tenant_id, "user_id": user_id})
                    if doc:
                        conn = self._doc_to_connection(doc)
                        self._connections[conn_id] = conn
                        return conn
                except Exception as err:
                    print(f"[GmailStore] Mongo get error: {err}")

            # In-memory fallback
            conn = self._connections.get(conn_id)
            if conn is None:
                conn = GmailConnection(
                    connection_id=conn_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    account_email=account_email or f"{user_id}@gmail.com",
                    status=GmailSyncStatus.AVAILABLE,
                    config=GmailSyncConfig(),
                    backfill_state=GmailBackfillState(),
                    lock=GmailLockState(),
                )
                self._connections[conn_id] = conn
                if self._db is not None:
                    try:
                        self._db.gmail_connections.update_one(
                            {"tenant_id": tenant_id, "user_id": user_id},
                            {"$set": conn.to_dict()},
                            upsert=True
                        )
                    except Exception as err:
                        print(f"[GmailStore] Mongo upsert error: {err}")
            return conn

    def update_connection(self, conn: GmailConnection) -> None:
        conn.updated_at = datetime.now(timezone.utc)
        with self._lock:
            self._connections[conn.connection_id] = conn
            if self._db is not None:
                try:
                    self._db.gmail_connections.update_one(
                        {"connection_id": conn.connection_id},
                        {"$set": conn.to_dict()},
                        upsert=True
                    )
                except Exception as err:
                    print(f"[GmailStore] Mongo update error: {err}")

    def acquire_lock(self, connection_id: str, job_id: str, lease_seconds: int = 900) -> bool:
        success = self._lock_manager.acquire_lock("gmail_connections", connection_id, job_id, lease_seconds)
        if success:
            with self._lock:
                conn = self._connections.get(connection_id)
                if conn:
                    conn.lock.is_locked = True
                    conn.lock.locked_by_job_id = job_id
                    conn.lock.locked_at = datetime.now(timezone.utc)
                    conn.lock.expires_at = conn.lock.locked_at + timedelta(seconds=lease_seconds)
        return success

    def release_lock(self, connection_id: str, job_id: str | None = None) -> None:
        self._lock_manager.release_lock("gmail_connections", connection_id, job_id)
        with self._lock:
            conn = self._connections.get(connection_id)
            if conn:
                if job_id is None or conn.lock.locked_by_job_id == job_id:
                    conn.lock.is_locked = False
                    conn.lock.locked_by_job_id = None
                    conn.lock.locked_at = None
                    conn.lock.expires_at = None

    def is_locked(self, connection_id: str) -> bool:
        return self._lock_manager.is_locked("gmail_connections", connection_id)

    def start_heartbeat(self, connection_id: str, job_id: str, lease_seconds: int = 900) -> None:
        self._lock_manager.start_heartbeat("gmail_connections", connection_id, job_id, lease_seconds)

    def stop_heartbeat(self, connection_id: str) -> None:
        self._lock_manager.stop_heartbeat(connection_id)

    def get_failed_items(self, connection_id: str) -> list[dict[str, Any]]:
        """Retrieves failed item records from recent activities for targeted retry."""
        failed_items = []
        activities = self.get_activities(connection_id, limit=5)
        seen_ids = set()
        for act in activities:
            for item in act.items:
                status = item.get("status") if isinstance(item, dict) else getattr(item, "status", None)
                if status == "FAILED":
                    item_id = item.get("message_id") or item.get("file_id") or item.get("id")
                    if item_id and item_id not in seen_ids:
                        seen_ids.add(item_id)
                        failed_items.append(item if isinstance(item, dict) else item.to_dict())
        return failed_items

    def is_message_synced(self, tenant_id: str, connection_id: str, message_id: str) -> bool:
        key = f"{tenant_id}:{connection_id}:{message_id}"
        with self._lock:
            if key in self._synced_messages:
                return True
            if self._db is not None:
                try:
                    count = self._db.gmail_synced_messages.count_documents({
                        "tenant_id": tenant_id,
                        "connection_id": connection_id,
                        "message_id": message_id,
                        "sync_status": {"$in": ["SUCCESS", "PARTIAL_SUCCESS"]}
                    })
                    return count > 0
                except Exception as err:
                    print(f"[GmailStore] Mongo deduplication check error: {err}")
            return False

    def record_synced_message(self, record: SyncedMessageRecord) -> None:
        key = f"{record.tenant_id}:{record.connection_id}:{record.message_id}"
        with self._lock:
            self._synced_messages[key] = record
            if self._db is not None:
                try:
                    self._db.gmail_synced_messages.update_one(
                        {"tenant_id": record.tenant_id, "connection_id": record.connection_id, "message_id": record.message_id},
                        {"$set": record.to_dict()},
                        upsert=True
                    )
                except Exception as err:
                    print(f"[GmailStore] Mongo record message error: {err}")

    def count_synced_messages(self, tenant_id: str, connection_id: str) -> int:
        with self._lock:
            if self._db is not None:
                try:
                    return self._db.gmail_synced_messages.count_documents({
                        "tenant_id": tenant_id,
                        "connection_id": connection_id,
                        "sync_status": {"$in": ["SUCCESS", "PARTIAL_SUCCESS"]}
                    })
                except Exception as err:
                    print(f"[GmailStore] Error counting messages: {err}")
            return sum(1 for k, v in self._synced_messages.items() if k.startswith(f"{tenant_id}:{connection_id}:") and v.sync_status in ("SUCCESS", "PARTIAL_SUCCESS"))

    def record_activity(self, activity: GmailSyncActivity) -> None:
        with self._lock:
            if activity.connection_id not in self._activities:
                self._activities[activity.connection_id] = []

            # Update existing activity in-place if already recorded (e.g. progress updates during batch processing)
            existing_idx = next(
                (i for i, a in enumerate(self._activities[activity.connection_id]) if a.activity_id == activity.activity_id),
                None,
            )
            if existing_idx is not None:
                self._activities[activity.connection_id][existing_idx] = activity
            else:
                self._activities[activity.connection_id].insert(0, activity)
                if len(self._activities[activity.connection_id]) > 50:
                    self._activities[activity.connection_id] = self._activities[activity.connection_id][:50]

            if self._db is not None:
                try:
                    self._db.gmail_sync_activities.update_one(
                        {"activity_id": activity.activity_id},
                        {"$set": activity.to_dict()},
                        upsert=True
                    )
                except Exception as err:
                    print(f"[GmailStore] Mongo record activity error: {err}")

    def get_activities(self, connection_id: str, limit: int = 20) -> list[GmailSyncActivity]:
        with self._lock:
            if self._db is not None:
                try:
                    docs = list(self._db.gmail_sync_activities.find({"connection_id": connection_id}).sort("started_at", -1).limit(limit))
                    if docs:
                        return [self._doc_to_activity(d) for d in docs]
                except Exception as err:
                    print(f"[GmailStore] Mongo get activities error: {err}")

            seen = set()
            deduped = []
            for act in self._activities.get(connection_id, []):
                if act.activity_id not in seen:
                    seen.add(act.activity_id)
                    deduped.append(act)
            return deduped[:limit]

    def list_all_active_connections(self) -> list[GmailConnection]:
        with self._lock:
            if self._db is not None:
                try:
                    docs = list(self._db.gmail_connections.find({"status": {"$ne": GmailSyncStatus.DISCONNECTED.value}}))
                    if docs:
                        return [self._doc_to_connection(d) for d in docs]
                except Exception as err:
                    print(f"[GmailStore] Mongo list connections error: {err}")
            return list(self._connections.values())

    def _doc_to_connection(self, doc: dict[str, Any]) -> GmailConnection:
        cfg = GmailSyncConfig.from_dict(doc.get("config", {}))
        backfill = GmailBackfillState.from_dict(doc.get("backfill_state", {}))
        lock = GmailLockState.from_dict(doc.get("lock", {}))
        status_val = doc.get("status", GmailSyncStatus.AVAILABLE.value)
        try:
            status_enum = GmailSyncStatus(status_val)
        except Exception:
            status_enum = GmailSyncStatus.AVAILABLE

        last_sync = None
        if doc.get("last_successful_sync_at"):
            try:
                last_sync = datetime.fromisoformat(doc["last_successful_sync_at"])
            except Exception:
                pass

        return GmailConnection(
            connection_id=doc.get("connection_id", ""),
            tenant_id=doc.get("tenant_id", "tenant_default"),
            user_id=doc.get("user_id", "usr_active"),
            account_email=doc.get("account_email", ""),
            status=status_enum,
            config=cfg,
            backfill_state=backfill,
            lock=lock,
            current_progress=doc.get("current_progress", ""),
            webhook_trigger_id=doc.get("webhook_trigger_id"),
            last_successful_sync_at=last_sync,
        )

    def _doc_to_activity(self, doc: dict[str, Any]) -> GmailSyncActivity:
        try:
            trig = GmailTriggerType(doc.get("trigger_type", "MANUAL_SYNC"))
        except Exception:
            trig = GmailTriggerType.MANUAL_SYNC

        started_at = datetime.now(timezone.utc)
        if doc.get("started_at"):
            try:
                started_at = datetime.fromisoformat(doc["started_at"])
            except Exception:
                pass

        completed_at = None
        if doc.get("completed_at"):
            try:
                completed_at = datetime.fromisoformat(doc["completed_at"])
            except Exception:
                pass

        return GmailSyncActivity(
            activity_id=doc.get("activity_id", ""),
            job_id=doc.get("job_id", ""),
            connection_id=doc.get("connection_id", ""),
            tenant_id=doc.get("tenant_id", "tenant_default"),
            trigger_type=trig,
            status=doc.get("status", "COMPLETED"),
            started_at=started_at,
            completed_at=completed_at,
            metrics=doc.get("metrics", {}),
            items=doc.get("items", []),
        )

    def get_data_summary(self, tenant_id: str, connection_id: str) -> dict[str, Any]:
        """Calculates current count of synced raw messages, activity runs, and state for pre-deletion preview."""
        with self._lock:
            msgs_count = 0
            activities_count = 0
            if self._db is not None:
                try:
                    msgs_count = self._db.gmail_synced_messages.count_documents({
                        "tenant_id": tenant_id,
                        "connection_id": connection_id,
                    })
                    activities_count = self._db.gmail_sync_activities.count_documents({
                        "connection_id": connection_id,
                    })
                except Exception as err:
                    print(f"[GmailStore] Error getting data summary from Mongo: {err}")
            else:
                msgs_count = sum(1 for k in self._synced_messages.keys() if k.startswith(f"{tenant_id}:{connection_id}:"))
                activities_count = len(self._activities.get(connection_id, []))

            conn = self._connections.get(connection_id)
            if not conn and self._db is not None:
                doc = self._db.gmail_connections.find_one({"connection_id": connection_id})
                if doc:
                    conn = self._doc_to_connection(doc)

            return {
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "synced_messages_count": msgs_count,
                "activities_count": activities_count,
                "is_backfill_complete": conn.backfill_state.is_backfill_complete if conn else False,
                "historical_status": conn.backfill_state.historical_sync_status.value if conn else "NOT_STARTED",
            }

    def purge_all_synced_data(self, tenant_id: str, connection_id: str) -> dict[str, int]:
        """
        Permanently purges all raw messages, activities, and resets watermarks in MongoDB and memory.
        Preserves connection authorization while resetting ingestion state to pristine.
        """
        from module_1_document_processing.composio_connector.gmail_models import HistoricalSyncStatus

        with self._lock:
            msgs_deleted = 0
            acts_deleted = 0

            # 1. MongoDB Deletions
            if self._db is not None:
                try:
                    r1 = self._db.gmail_synced_messages.delete_many({
                        "tenant_id": tenant_id,
                        "connection_id": connection_id,
                    })
                    msgs_deleted = r1.deleted_count

                    r2 = self._db.gmail_sync_activities.delete_many({
                        "connection_id": connection_id,
                    })
                    acts_deleted = r2.deleted_count
                    print(f"[GmailStore] Purged {msgs_deleted} messages and {acts_deleted} activities from MongoDB for {connection_id}.")
                except Exception as err:
                    print(f"[GmailStore] Error purging from Mongo: {err}")

            # 2. In-Memory Deletions
            keys_to_del = [k for k in self._synced_messages.keys() if k.startswith(f"{tenant_id}:{connection_id}:")]
            for k in keys_to_del:
                self._synced_messages.pop(k, None)
            if not msgs_deleted:
                msgs_deleted = len(keys_to_del)

            if connection_id in self._activities:
                if not acts_deleted:
                    acts_deleted = len(self._activities[connection_id])
                self._activities[connection_id] = []

            # 3. Reset Connection Watermarks & Backfill State
            conn = self._connections.get(connection_id)
            if not conn and self._db is not None:
                doc = self._db.gmail_connections.find_one({"connection_id": connection_id})
                if doc:
                    conn = self._doc_to_connection(doc)
                    self._connections[connection_id] = conn

            if conn:
                conn.backfill_state.historical_sync_status = HistoricalSyncStatus.NOT_STARTED
                conn.backfill_state.is_backfill_complete = False
                conn.backfill_state.newest_synced_timestamp = None
                conn.backfill_state.oldest_synced_timestamp = None
                conn.backfill_state.historical_sync_cursor = None
                conn.backfill_state.next_page_token = None
                conn.backfill_state.historical_sync_boundary = None
                conn.backfill_state.total_eligible_discovered = 0
                conn.backfill_state.total_synced_so_far = 0
                conn.backfill_state.total_duplicate_skipped = 0
                conn.current_progress = ""
                conn.last_successful_sync_at = None
                self.update_connection(conn)

            return {
                "synced_messages_deleted": msgs_deleted,
                "activities_deleted": acts_deleted,
            }
