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
        if MongoClient and self.mongo_uri:
            try:
                self._mongo_client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=500)
                # Verify live connection immediately with ping
                self._mongo_client.admin.command("ping")
                self._db = self._mongo_client[self.db_name]
                # Ensure compound unique index for deduplication
                self._db.gmail_synced_messages.create_index(
                    [("tenant_id", ASCENDING), ("connection_id", ASCENDING), ("message_id", ASCENDING)],
                    unique=True
                )
                self._db.gmail_connections.create_index([("tenant_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
                print(f"[GmailStore] Initialized MongoDB collections at {self.mongo_uri}/{self.db_name}")
            except Exception as err:
                print(f"[GmailStore] Using fast in-memory store (MongoDB offline / local mode: {err})")
                self._db = None
                self._mongo_client = None

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
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=lease_seconds)
        with self._lock:
            conn = self._connections.get(connection_id)
            if not conn:
                return False

            # Check if locked and lease is still valid
            if conn.lock.is_locked and conn.lock.expires_at and conn.lock.expires_at > now:
                if conn.lock.locked_by_job_id == job_id:
                    # Same job re-acquiring/extending
                    conn.lock.expires_at = expires_at
                    self.update_connection(conn)
                    return True
                return False  # Locked by another job

            # Acquire lock
            conn.lock.is_locked = True
            conn.lock.locked_by_job_id = job_id
            conn.lock.locked_at = now
            conn.lock.expires_at = expires_at
            self.update_connection(conn)
            return True

    def release_lock(self, connection_id: str, job_id: str | None = None) -> None:
        with self._lock:
            conn = self._connections.get(connection_id)
            if conn:
                if job_id is None or conn.lock.locked_by_job_id == job_id:
                    conn.lock.is_locked = False
                    conn.lock.locked_by_job_id = None
                    conn.lock.locked_at = None
                    conn.lock.expires_at = None
                    self.update_connection(conn)

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

    def record_activity(self, activity: GmailSyncActivity) -> None:
        with self._lock:
            if activity.connection_id not in self._activities:
                self._activities[activity.connection_id] = []
            # Prepend newest activity
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

            return self._activities.get(connection_id, [])[:limit]

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
