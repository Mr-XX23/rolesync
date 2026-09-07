import os
import threading
from datetime import datetime, timezone, timedelta
from typing import Any

from module_1_document_processing.composio_connector.calendar_models import (
    CalendarConnection,
    CalendarSyncConfig,
    CalendarBackfillState,
    CalendarLockState,
    CalendarSyncStatus,
    CalendarTriggerType,
    HistoricalSyncStatus,
    SyncPhase,
    SyncedEventRecord,
    CalendarSyncActivity,
)

try:
    from pymongo import MongoClient, ASCENDING
except ImportError:
    MongoClient = None
    ASCENDING = 1

class CalendarStore:
    """MongoDB & In-Memory Store managing Google Calendar connections, event deduplication, locks, and sync activity logs."""

    def __init__(self) -> None:
        self.mongo_uri = os.environ.get("MONGODB_URI", "mongodb://mongodb:27017")
        self.db_name = os.environ.get("MONGODB_DB_NAME", "rolesync_rag")
        self._lock = threading.RLock()

        # In-memory fallback stores
        self._connections: dict[str, CalendarConnection] = {}
        self._synced_events: dict[str, SyncedEventRecord] = {}  # key: f"{tenant_id}:{connection_id}:{event_id}"
        self._activities: dict[str, list[CalendarSyncActivity]] = {}  # key: connection_id -> list

        self._mongo_client = None
        self._db = None
        if MongoClient and self.mongo_uri:
            try:
                self._mongo_client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=500)
                self._mongo_client.admin.command("ping")
                self._db = self._mongo_client[self.db_name]
                # Compound unique index for event deduplication
                self._db.calendar_synced_events.create_index(
                    [("tenant_id", ASCENDING), ("connection_id", ASCENDING), ("event_id", ASCENDING)],
                    unique=True,
                )
                self._db.calendar_synced_events.create_index([("tenant_id", ASCENDING), ("connection_id", ASCENDING), ("start_time", -1)])
                self._db.calendar_connections.create_index([("tenant_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
                self._db.calendar_sync_activities.create_index([("connection_id", ASCENDING), ("started_at", -1)])
                print(f"[CalendarStore] Initialized MongoDB collections and compound indexes at {self.mongo_uri}/{self.db_name}")
            except Exception as err:
                print(f"[CalendarStore] Using fast in-memory store (MongoDB offline / local mode: {err})")
                self._db = None
                self._mongo_client = None

    def get_or_create_connection(self, tenant_id: str, user_id: str, account_email: str = "") -> CalendarConnection:
        conn_id = f"conn_calendar_{tenant_id}_{user_id}"
        with self._lock:
            # Check MongoDB first
            if self._db is not None:
                try:
                    doc = self._db.calendar_connections.find_one({"tenant_id": tenant_id, "user_id": user_id})
                    if doc:
                        conn = self._doc_to_connection(doc)
                        self._connections[conn_id] = conn
                        return conn
                except Exception as err:
                    print(f"[CalendarStore] Mongo get error: {err}")

            # In-memory fallback
            conn = self._connections.get(conn_id)
            if conn is None:
                conn = CalendarConnection(
                    connection_id=conn_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    account_email=account_email or f"{user_id}@gmail.com",
                    status=CalendarSyncStatus.AVAILABLE,
                    config=CalendarSyncConfig(),
                    backfill_state=CalendarBackfillState(),
                    lock=CalendarLockState(),
                )
                self._connections[conn_id] = conn
                if self._db is not None:
                    try:
                        self._db.calendar_connections.update_one(
                            {"tenant_id": tenant_id, "user_id": user_id},
                            {"$set": conn.to_dict()},
                            upsert=True,
                        )
                    except Exception as err:
                        print(f"[CalendarStore] Mongo upsert error: {err}")
            return conn

    def update_connection(self, conn: CalendarConnection) -> None:
        conn.updated_at = datetime.now(timezone.utc)
        with self._lock:
            self._connections[conn.connection_id] = conn
            if self._db is not None:
                try:
                    self._db.calendar_connections.update_one(
                        {"connection_id": conn.connection_id},
                        {"$set": conn.to_dict()},
                        upsert=True,
                    )
                except Exception as err:
                    print(f"[CalendarStore] Mongo update error: {err}")

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
                doc = self._db.calendar_connections.find_one({"connection_id": connection_id})
                if doc:
                    conn = self._doc_to_connection(doc)
                    self._connections[connection_id] = conn

            if not conn:
                return False
            return bool(conn.lock.is_locked and conn.lock.expires_at and conn.lock.expires_at > now)

    def is_event_synced(self, tenant_id: str, connection_id: str, event_id: str) -> bool:
        key = f"{tenant_id}:{connection_id}:{event_id}"
        with self._lock:
            if key in self._synced_events:
                return True
            if self._db is not None:
                try:
                    count = self._db.calendar_synced_events.count_documents(
                        {"tenant_id": tenant_id, "connection_id": connection_id, "event_id": event_id},
                        limit=1,
                    )
                    return count > 0
                except Exception as err:
                    print(f"[CalendarStore] Mongo is_event_synced error: {err}")
            return False

    def record_synced_event(self, record: SyncedEventRecord) -> None:
        key = f"{record.tenant_id}:{record.connection_id}:{record.event_id}"
        with self._lock:
            self._synced_events[key] = record
            if self._db is not None:
                try:
                    self._db.calendar_synced_events.update_one(
                        {
                            "tenant_id": record.tenant_id,
                            "connection_id": record.connection_id,
                            "event_id": record.event_id,
                        },
                        {"$set": record.to_dict()},
                        upsert=True,
                    )
                except Exception as err:
                    print(f"[CalendarStore] Mongo record_synced_event error: {err}")

    def delete_synced_event(self, tenant_id: str, connection_id: str, event_id: str) -> None:
        key = f"{tenant_id}:{connection_id}:{event_id}"
        with self._lock:
            self._synced_events.pop(key, None)
            if self._db is not None:
                try:
                    self._db.calendar_synced_events.delete_one(
                        {"tenant_id": tenant_id, "connection_id": connection_id, "event_id": event_id}
                    )
                except Exception as err:
                    print(f"[CalendarStore] Mongo delete_synced_event error: {err}")

    def count_synced_events(self, tenant_id: str, connection_id: str) -> int:
        with self._lock:
            if self._db is not None:
                try:
                    return self._db.calendar_synced_events.count_documents(
                        {"tenant_id": tenant_id, "connection_id": connection_id}
                    )
                except Exception as err:
                    print(f"[CalendarStore] Mongo count error: {err}")
            return sum(
                1 for k in self._synced_events.keys() if k.startswith(f"{tenant_id}:{connection_id}:")
            )

    def record_activity(self, activity: CalendarSyncActivity) -> None:
        with self._lock:
            acts = self._activities.setdefault(activity.connection_id, [])
            # Update existing or prepend
            for idx, act in enumerate(acts):
                if act.activity_id == activity.activity_id:
                    acts[idx] = activity
                    break
            else:
                acts.insert(0, activity)

            if self._db is not None:
                try:
                    self._db.calendar_sync_activities.update_one(
                        {"activity_id": activity.activity_id},
                        {"$set": activity.to_dict()},
                        upsert=True,
                    )
                except Exception as err:
                    print(f"[CalendarStore] Mongo activity error: {err}")

    def get_activities(self, connection_id: str, limit: int = 20) -> list[CalendarSyncActivity]:
        with self._lock:
            if self._db is not None:
                try:
                    cursor = (
                        self._db.calendar_sync_activities.find({"connection_id": connection_id})
                        .sort("started_at", -1)
                        .limit(limit)
                    )
                    return [self._doc_to_activity(d) for d in cursor]
                except Exception as err:
                    print(f"[CalendarStore] Mongo get_activities error: {err}")

            return self._activities.get(connection_id, [])[:limit]

    def get_data_summary(self, tenant_id: str, connection_id: str) -> dict[str, Any]:
        with self._lock:
            if self._db is not None:
                try:
                    events_count = self._db.calendar_synced_events.count_documents(
                        {"tenant_id": tenant_id, "connection_id": connection_id}
                    )
                    activities_count = self._db.calendar_sync_activities.count_documents(
                        {"connection_id": connection_id}
                    )
                except Exception as err:
                    print(f"[CalendarStore] Mongo data summary count error: {err}")
                    events_count = sum(1 for k in self._synced_events.keys() if k.startswith(f"{tenant_id}:{connection_id}:"))
                    activities_count = len(self._activities.get(connection_id, []))
            else:
                events_count = sum(1 for k in self._synced_events.keys() if k.startswith(f"{tenant_id}:{connection_id}:"))
                activities_count = len(self._activities.get(connection_id, []))

            conn = self._connections.get(connection_id)
            if not conn and self._db is not None:
                doc = self._db.calendar_connections.find_one({"connection_id": connection_id})
                if doc:
                    conn = self._doc_to_connection(doc)

            return {
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "synced_messages_count": events_count,
                "synced_events_count": events_count,
                "activities_count": activities_count,
                "is_backfill_complete": conn.backfill_state.is_backfill_complete if conn else False,
                "historical_status": conn.backfill_state.historical_sync_status.value if conn else "NOT_STARTED",
            }

    def purge_all_synced_data(self, tenant_id: str, user_id: str) -> dict[str, int]:
        """Cascades purge of all indexed calendar records, activities, and resets watermarks."""
        conn_id = f"conn_calendar_{tenant_id}_{user_id}"
        events_deleted = 0
        activities_deleted = 0

        with self._lock:
            # 1. Clear memory stores
            keys_to_remove = [k for k in self._synced_events.keys() if k.startswith(f"{tenant_id}:{conn_id}:")]
            for k in keys_to_remove:
                del self._synced_events[k]
            events_deleted = len(keys_to_remove)

            acts = self._activities.pop(conn_id, [])
            activities_deleted = len(acts)

            # 2. Clear MongoDB collections
            if self._db is not None:
                try:
                    res_e = self._db.calendar_synced_events.delete_many(
                        {"tenant_id": tenant_id, "connection_id": conn_id}
                    )
                    events_deleted = max(events_deleted, res_e.deleted_count)

                    res_a = self._db.calendar_sync_activities.delete_many({"connection_id": conn_id})
                    activities_deleted = max(activities_deleted, res_a.deleted_count)
                except Exception as err:
                    print(f"[CalendarStore] Mongo purge error: {err}")

            # 3. Reset Connection Watermarks
            conn = self.get_or_create_connection(tenant_id, user_id)
            conn.backfill_state = CalendarBackfillState()
            conn.last_successful_sync_at = None
            conn.current_progress = "All calendar data purged"
            conn.status = CalendarSyncStatus.CONNECTED
            self.update_connection(conn)

            return {
                "events_deleted": events_deleted,
                "activities_deleted": activities_deleted,
            }

    def list_all_active_connections(self) -> list[CalendarConnection]:
        with self._lock:
            if self._db is not None:
                try:
                    docs = list(self._db.calendar_connections.find({"status": {"$ne": CalendarSyncStatus.DISCONNECTED.value}}))
                    if docs:
                        conns = [self._doc_to_connection(d) for d in docs]
                        for c in conns:
                            self._connections[c.connection_id] = c
                        return conns
                except Exception as err:
                    print(f"[CalendarStore] Mongo list connections error: {err}")
            return list(self._connections.values())

    def _doc_to_connection(self, doc: dict[str, Any]) -> CalendarConnection:
        conn = CalendarConnection(
            connection_id=doc.get("connection_id", ""),
            tenant_id=doc.get("tenant_id", "tenant_default"),
            user_id=doc.get("user_id", ""),
            account_email=doc.get("account_email", ""),
            status=CalendarSyncStatus(doc.get("status", CalendarSyncStatus.AVAILABLE)),
            config=CalendarSyncConfig.from_dict(doc.get("config", {})),
            backfill_state=CalendarBackfillState.from_dict(doc.get("backfill_state", {})),
            lock=CalendarLockState.from_dict(doc.get("lock", {})),
            current_progress=doc.get("current_progress", ""),
            webhook_trigger_id=doc.get("webhook_trigger_id"),
        )
        if doc.get("last_successful_sync_at"):
            try:
                conn.last_successful_sync_at = datetime.fromisoformat(doc["last_successful_sync_at"])
            except Exception:
                pass
        return conn

    def _doc_to_activity(self, doc: dict[str, Any]) -> CalendarSyncActivity:
        act = CalendarSyncActivity(
            activity_id=doc.get("activity_id", ""),
            job_id=doc.get("job_id", ""),
            connection_id=doc.get("connection_id", ""),
            tenant_id=doc.get("tenant_id", "tenant_default"),
            trigger_type=CalendarTriggerType(doc.get("trigger_type", CalendarTriggerType.MANUAL_SYNC)),
            status=doc.get("status", "COMPLETED"),
            metrics=doc.get("metrics", {}),
            items=doc.get("items", []),
        )
        if doc.get("started_at"):
            try:
                act.started_at = datetime.fromisoformat(doc["started_at"])
            except Exception:
                pass
        if doc.get("completed_at"):
            try:
                act.completed_at = datetime.fromisoformat(doc["completed_at"])
            except Exception:
                pass
        return act
