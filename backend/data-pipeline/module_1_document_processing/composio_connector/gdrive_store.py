import os
import threading
from datetime import datetime, timezone, timedelta
from typing import Any

from module_1_document_processing.composio_connector.gdrive_models import (
    GDriveConnection,
    GDriveSyncConfig,
    GDriveBackfillState,
    GDriveLockState,
    GDriveSyncStatus,
    GDriveTriggerType,
    HistoricalSyncStatus,
    SyncedFileRecord,
    GDriveSyncActivity,
)

try:
    from pymongo import MongoClient, ASCENDING
except ImportError:
    MongoClient = None
    ASCENDING = 1

class GDriveStore:
    """MongoDB & In-Memory Store managing Google Drive connections, file deduplication, locks, and sync activity logs."""

    def __init__(self) -> None:
        self.mongo_uri = os.environ.get("MONGODB_URI", "mongodb://mongodb:27017")
        self.db_name = os.environ.get("MONGODB_DB_NAME", "rolesync_rag")
        self._lock = threading.RLock()

        # In-memory fallback stores
        self._connections: dict[str, GDriveConnection] = {}
        self._synced_files: dict[str, SyncedFileRecord] = {}  # key: f"{tenant_id}:{connection_id}:{file_id}"
        self._activities: dict[str, list[GDriveSyncActivity]] = {}  # key: connection_id -> list

        self._mongo_client = None
        self._db = None
        if MongoClient and self.mongo_uri:
            try:
                self._mongo_client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=500)
                self._mongo_client.admin.command("ping")
                self._db = self._mongo_client[self.db_name]
                # Compound unique index for file deduplication
                self._db.gdrive_synced_files.create_index(
                    [("tenant_id", ASCENDING), ("connection_id", ASCENDING), ("file_id", ASCENDING)],
                    unique=True
                )
                self._db.gdrive_synced_files.create_index([("tenant_id", ASCENDING), ("connection_id", ASCENDING), ("modified_at", -1)])
                self._db.gdrive_connections.create_index([("tenant_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
                self._db.gdrive_sync_activities.create_index([("connection_id", ASCENDING), ("started_at", -1)])
                print(f"[GDriveStore] Initialized MongoDB collections and compound indexes at {self.mongo_uri}/{self.db_name}")
            except Exception as err:
                print(f"[GDriveStore] Using in-memory store (MongoDB offline / local mode: {err})")
                self._db = None
                self._mongo_client = None

    def get_or_create_connection(self, tenant_id: str, user_id: str, account_email: str = "") -> GDriveConnection:
        conn_id = f"conn_gdrive_{tenant_id}_{user_id}"
        with self._lock:
            # Check MongoDB first
            if self._db is not None:
                try:
                    doc = self._db.gdrive_connections.find_one({"tenant_id": tenant_id, "user_id": user_id})
                    if doc:
                        conn = self._doc_to_connection(doc)
                        self._connections[conn_id] = conn
                        return conn
                except Exception as err:
                    print(f"[GDriveStore] Mongo get error: {err}")

            # In-memory fallback
            conn = self._connections.get(conn_id)
            if conn is None:
                conn = GDriveConnection(
                    connection_id=conn_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    account_email=account_email or f"{user_id}@gmail.com",
                    status=GDriveSyncStatus.AVAILABLE,
                    config=GDriveSyncConfig(),
                    backfill_state=GDriveBackfillState(),
                    lock=GDriveLockState(),
                )
                self._connections[conn_id] = conn
                if self._db is not None:
                    try:
                        self._db.gdrive_connections.update_one(
                            {"tenant_id": tenant_id, "user_id": user_id},
                            {"$set": conn.to_dict()},
                            upsert=True
                        )
                    except Exception as err:
                        print(f"[GDriveStore] Mongo upsert error: {err}")
            return conn

    def update_connection(self, conn: GDriveConnection) -> None:
        conn.updated_at = datetime.now(timezone.utc)
        with self._lock:
            self._connections[conn.connection_id] = conn
            if self._db is not None:
                try:
                    self._db.gdrive_connections.update_one(
                        {"connection_id": conn.connection_id},
                        {"$set": conn.to_dict()},
                        upsert=True
                    )
                except Exception as err:
                    print(f"[GDriveStore] Mongo update error: {err}")

    def acquire_lock(self, connection_id: str, job_id: str, lease_seconds: int = 900) -> bool:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=lease_seconds)
        with self._lock:
            conn = self._connections.get(connection_id)
            if not conn:
                return False

            if conn.lock.is_locked and conn.lock.expires_at and conn.lock.expires_at > now:
                if conn.lock.locked_by_job_id == job_id:
                    conn.lock.expires_at = expires_at
                    self.update_connection(conn)
                    return True
                return False

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

    def is_locked(self, connection_id: str) -> bool:
        now = datetime.now(timezone.utc)
        with self._lock:
            conn = self._connections.get(connection_id)
            if not conn and self._db is not None:
                doc = self._db.gdrive_connections.find_one({"connection_id": connection_id})
                if doc:
                    conn = self._doc_to_connection(doc)
                    self._connections[connection_id] = conn
            if not conn:
                return False
            return bool(conn.lock.is_locked and conn.lock.expires_at and conn.lock.expires_at > now)

    def is_file_synced(self, tenant_id: str, connection_id: str, file_id: str) -> bool:
        key = f"{tenant_id}:{connection_id}:{file_id}"
        with self._lock:
            if key in self._synced_files:
                return True
            if self._db is not None:
                try:
                    count = self._db.gdrive_synced_files.count_documents({
                        "tenant_id": tenant_id,
                        "connection_id": connection_id,
                        "file_id": file_id,
                        "sync_status": {"$in": ["SUCCESS", "PARTIAL_SUCCESS"]}
                    })
                    return count > 0
                except Exception as err:
                    print(f"[GDriveStore] Mongo deduplication check error: {err}")
            return False

    def record_synced_file(self, record: SyncedFileRecord) -> None:
        key = f"{record.tenant_id}:{record.connection_id}:{record.file_id}"
        with self._lock:
            self._synced_files[key] = record
            if self._db is not None:
                try:
                    self._db.gdrive_synced_files.update_one(
                        {"tenant_id": record.tenant_id, "connection_id": record.connection_id, "file_id": record.file_id},
                        {"$set": record.to_dict()},
                        upsert=True
                    )
                except Exception as err:
                    print(f"[GDriveStore] Mongo record file error: {err}")

    def count_synced_files(self, tenant_id: str, connection_id: str) -> int:
        with self._lock:
            if self._db is not None:
                try:
                    return self._db.gdrive_synced_files.count_documents({
                        "tenant_id": tenant_id,
                        "connection_id": connection_id,
                        "sync_status": {"$in": ["SUCCESS", "PARTIAL_SUCCESS"]}
                    })
                except Exception as err:
                    print(f"[GDriveStore] Error counting files: {err}")
            return sum(1 for k, v in self._synced_files.items() if k.startswith(f"{tenant_id}:{connection_id}:") and v.sync_status in ("SUCCESS", "PARTIAL_SUCCESS"))

    def record_activity(self, activity: GDriveSyncActivity) -> None:
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
                    self._db.gdrive_sync_activities.update_one(
                        {"activity_id": activity.activity_id},
                        {"$set": activity.to_dict()},
                        upsert=True
                    )
                except Exception as err:
                    print(f"[GDriveStore] Mongo record activity error: {err}")

    def get_activities(self, connection_id: str, limit: int = 20) -> list[GDriveSyncActivity]:
        with self._lock:
            if self._db is not None:
                try:
                    docs = list(self._db.gdrive_sync_activities.find({"connection_id": connection_id}).sort("started_at", -1).limit(limit))
                    if docs:
                        return [self._doc_to_activity(d) for d in docs]
                except Exception as err:
                    print(f"[GDriveStore] Mongo get activities error: {err}")

            seen = set()
            deduped = []
            for act in self._activities.get(connection_id, []):
                if act.activity_id not in seen:
                    seen.add(act.activity_id)
                    deduped.append(act)
            return deduped[:limit]

    def list_all_active_connections(self) -> list[GDriveConnection]:
        with self._lock:
            if self._db is not None:
                try:
                    docs = list(self._db.gdrive_connections.find({"status": {"$ne": GDriveSyncStatus.DISCONNECTED.value}}))
                    if docs:
                        return [self._doc_to_connection(d) for d in docs]
                except Exception as err:
                    print(f"[GDriveStore] Mongo list connections error: {err}")
            return list(self._connections.values())

    def _doc_to_connection(self, doc: dict[str, Any]) -> GDriveConnection:
        cfg = GDriveSyncConfig.from_dict(doc.get("config", {}))
        backfill = GDriveBackfillState.from_dict(doc.get("backfill_state", {}))
        lock = GDriveLockState.from_dict(doc.get("lock", {}))

        raw_status = doc.get("status", GDriveSyncStatus.AVAILABLE.value)
        try:
            status = GDriveSyncStatus(raw_status)
        except Exception:
            status = GDriveSyncStatus.AVAILABLE

        created_at = datetime.now(timezone.utc)
        if doc.get("created_at"):
            try:
                created_at = datetime.fromisoformat(doc["created_at"])
            except Exception:
                pass

        updated_at = datetime.now(timezone.utc)
        if doc.get("updated_at"):
            try:
                updated_at = datetime.fromisoformat(doc["updated_at"])
            except Exception:
                pass

        last_sync = None
        if doc.get("last_successful_sync_at"):
            try:
                last_sync = datetime.fromisoformat(doc["last_successful_sync_at"])
            except Exception:
                pass

        return GDriveConnection(
            connection_id=doc.get("connection_id", ""),
            tenant_id=doc.get("tenant_id", "tenant_default"),
            user_id=doc.get("user_id", "usr_active"),
            account_email=doc.get("account_email", ""),
            status=status,
            config=cfg,
            backfill_state=backfill,
            lock=lock,
            current_progress=doc.get("current_progress", ""),
            webhook_trigger_id=doc.get("webhook_trigger_id"),
            last_successful_sync_at=last_sync,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _doc_to_activity(self, doc: dict[str, Any]) -> GDriveSyncActivity:
        trig_raw = doc.get("trigger_type", GDriveTriggerType.AUTO_SYNC.value)
        try:
            trig = GDriveTriggerType(trig_raw)
        except Exception:
            trig = GDriveTriggerType.AUTO_SYNC

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

        return GDriveSyncActivity(
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
        with self._lock:
            files_count = 0
            activities_count = 0
            if self._db is not None:
                try:
                    files_count = self._db.gdrive_synced_files.count_documents({
                        "tenant_id": tenant_id,
                        "connection_id": connection_id,
                    })
                    activities_count = self._db.gdrive_sync_activities.count_documents({
                        "connection_id": connection_id,
                    })
                except Exception as err:
                    print(f"[GDriveStore] Error getting data summary from Mongo: {err}")
            else:
                files_count = sum(1 for k in self._synced_files.keys() if k.startswith(f"{tenant_id}:{connection_id}:"))
                activities_count = len(self._activities.get(connection_id, []))

            conn = self._connections.get(connection_id)
            if not conn and self._db is not None:
                doc = self._db.gdrive_connections.find_one({"connection_id": connection_id})
                if doc:
                    conn = self._doc_to_connection(doc)

            return {
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "synced_messages_count": files_count,  # standard key for UI modal
                "synced_files_count": files_count,
                "activities_count": activities_count,
                "is_backfill_complete": conn.backfill_state.is_backfill_complete if conn else False,
                "historical_status": conn.backfill_state.historical_sync_status.value if conn else "NOT_STARTED",
            }

    def purge_all_synced_data(self, tenant_id: str, connection_id: str) -> dict[str, int]:
        with self._lock:
            files_deleted = 0
            acts_deleted = 0

            if self._db is not None:
                try:
                    r1 = self._db.gdrive_synced_files.delete_many({
                        "tenant_id": tenant_id,
                        "connection_id": connection_id,
                    })
                    files_deleted = r1.deleted_count

                    r2 = self._db.gdrive_sync_activities.delete_many({
                        "connection_id": connection_id,
                    })
                    acts_deleted = r2.deleted_count
                    print(f"[GDriveStore] Purged {files_deleted} files and {acts_deleted} activities from MongoDB for {connection_id}.")
                except Exception as err:
                    print(f"[GDriveStore] Error purging from Mongo: {err}")

            keys_to_del = [k for k in self._synced_files.keys() if k.startswith(f"{tenant_id}:{connection_id}:")]
            for k in keys_to_del:
                self._synced_files.pop(k, None)
            if not files_deleted:
                files_deleted = len(keys_to_del)

            if connection_id in self._activities:
                if not acts_deleted:
                    acts_deleted = len(self._activities[connection_id])
                self._activities[connection_id] = []

            conn = self._connections.get(connection_id)
            if not conn and self._db is not None:
                doc = self._db.gdrive_connections.find_one({"connection_id": connection_id})
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
                conn.backfill_state.total_eligible_discovered = 0
                conn.backfill_state.total_synced_so_far = 0
                conn.current_progress = ""
                conn.last_successful_sync_at = None
                self.update_connection(conn)

            return {
                "synced_files_deleted": files_deleted,
                "activities_deleted": acts_deleted,
            }
