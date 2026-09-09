import os
import threading
from datetime import datetime, timezone, timedelta
from typing import Any
from module_1_document_processing.composio_connector.slack_models import (
    SlackConnection,
    SlackSyncStatus,
    SlackSyncConfig,
    SlackBackfillState,
    SlackLockState,
    SyncedSlackMessageRecord,
    SlackSyncActivity,
    SlackTriggerType,
)

try:
    from pymongo import MongoClient, ASCENDING
except ImportError:
    MongoClient = None
    ASCENDING = 1

from module_1_document_processing.composio_connector.distributed_lock import DistributedLockManager

class SlackStore:
    """MongoDB & In-Memory Store managing Slack connections, deduplication, locks, and sync activity logs."""

    def __init__(self) -> None:
        self.mongo_uri = os.environ.get("MONGODB_URI", "mongodb://mongodb:27017")
        self.db_name = os.environ.get("MONGODB_DB_NAME", "rolesync_rag")
        self._lock = threading.RLock()

        # In-memory stores
        self._connections: dict[str, SlackConnection] = {}
        self._synced_messages: dict[str, SyncedSlackMessageRecord] = {}  # key: f"{tenant_id}:{connection_id}:{message_id}"
        self._activities: dict[str, list[SlackSyncActivity]] = {}  # key: connection_id -> list

        self._mongo_client = None
        self._db = None
        self._lock_manager = DistributedLockManager(db=None)
        if MongoClient and self.mongo_uri:
            try:
                self._mongo_client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=500)
                self._mongo_client.admin.command("ping")
                self._db = self._mongo_client[self.db_name]
                self._lock_manager.set_db(self._db)
                # Compound unique index for bulletproof deduplication
                self._db.slack_synced_messages.create_index(
                    [("tenant_id", ASCENDING), ("connection_id", ASCENDING), ("message_id", ASCENDING)],
                    unique=True
                )
                self._db.slack_synced_messages.create_index([("tenant_id", ASCENDING), ("connection_id", ASCENDING), ("received_at", -1)])
                self._db.slack_connections.create_index([("tenant_id", ASCENDING), ("user_id", ASCENDING)], unique=True)
                self._db.slack_sync_activities.create_index([("connection_id", ASCENDING), ("started_at", -1)])
                print(f"[SlackStore] Initialized MongoDB collections and compound indexes at {self.mongo_uri}/{self.db_name}")
            except Exception as err:
                print(f"[SlackStore] Using fast in-memory store (MongoDB offline / local mode: {err})")
                self._db = None
                self._mongo_client = None
                self._lock_manager.set_db(None)

    def get_or_create_connection(self, tenant_id: str, user_id: str, account_name: str = "") -> SlackConnection:
        conn_id = f"conn_slack_{tenant_id}_{user_id}"
        with self._lock:
            if self._db is not None:
                try:
                    doc = self._db.slack_connections.find_one({"tenant_id": tenant_id, "user_id": user_id})
                    if doc:
                        conn = self._doc_to_connection(doc)
                        self._connections[conn_id] = conn
                        return conn
                except Exception as err:
                    print(f"[SlackStore] Mongo get error: {err}")

            conn = self._connections.get(conn_id)
            if conn is None:
                conn = SlackConnection(
                    connection_id=conn_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    account_name=account_name or f"{user_id}_slack",
                    status=SlackSyncStatus.AVAILABLE,
                    config=SlackSyncConfig(),
                    backfill_state=SlackBackfillState(),
                    lock=SlackLockState(),
                )
                self._connections[conn_id] = conn
                if self._db is not None:
                    try:
                        self._db.slack_connections.update_one(
                            {"tenant_id": tenant_id, "user_id": user_id},
                            {"$set": conn.to_dict()},
                            upsert=True
                        )
                    except Exception as err:
                        print(f"[SlackStore] Mongo upsert error: {err}")
            return conn

    def get_connection(self, tenant_id: str, user_id: str) -> SlackConnection | None:
        conn_id = f"conn_slack_{tenant_id}_{user_id}"
        with self._lock:
            if self._db is not None:
                try:
                    doc = self._db.slack_connections.find_one({"tenant_id": tenant_id, "user_id": user_id})
                    if doc:
                        conn = self._doc_to_connection(doc)
                        self._connections[conn_id] = conn
                        return conn
                except Exception as err:
                    print(f"[SlackStore] Mongo get error: {err}")
            return self._connections.get(conn_id)

    def find_connection_by_trigger_id(self, trigger_id: str) -> SlackConnection | None:
        if not trigger_id:
            return None
        with self._lock:
            if self._db is not None:
                try:
                    doc = self._db.slack_connections.find_one({"webhook_trigger_id": trigger_id})
                    if doc:
                        conn = self._doc_to_connection(doc)
                        self._connections[conn.connection_id] = conn
                        return conn
                except Exception as err:
                    print(f"[SlackStore] Mongo find trigger error: {err}")
            for c in self._connections.values():
                if c.webhook_trigger_id == trigger_id:
                    return c
            return None

    def find_active_webhook_connection(self, tenant_id: str | None = None) -> SlackConnection | None:
        with self._lock:
            if self._db is not None:
                try:
                    query: dict[str, Any] = {"config.webhook_enabled": True}
                    if tenant_id:
                        query["tenant_id"] = tenant_id
                    doc = self._db.slack_connections.find_one(query)
                    if doc:
                        conn = self._doc_to_connection(doc)
                        self._connections[conn.connection_id] = conn
                        return conn
                except Exception as err:
                    print(f"[SlackStore] Mongo find webhook conn error: {err}")
            for c in self._connections.values():
                if getattr(c.config, "webhook_enabled", False):
                    if not tenant_id or c.tenant_id == tenant_id:
                        return c
            return None

    def update_connection(self, conn: SlackConnection) -> None:
        conn.updated_at = datetime.now(timezone.utc)
        with self._lock:
            self._connections[conn.connection_id] = conn
            if self._db is not None:
                try:
                    self._db.slack_connections.update_one(
                        {"connection_id": conn.connection_id},
                        {"$set": conn.to_dict()},
                        upsert=True
                    )
                except Exception as err:
                    print(f"[SlackStore] Mongo update error: {err}")

    def acquire_lock(self, connection_id: str, job_id: str, lease_seconds: int = 900) -> bool:
        success = self._lock_manager.acquire_lock("slack_connections", connection_id, job_id, lease_seconds)
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
        self._lock_manager.release_lock("slack_connections", connection_id, job_id)
        with self._lock:
            conn = self._connections.get(connection_id)
            if conn:
                if job_id is None or conn.lock.locked_by_job_id == job_id:
                    conn.lock.is_locked = False
                    conn.lock.locked_by_job_id = None
                    conn.lock.locked_at = None
                    conn.lock.expires_at = None

    def is_locked(self, connection_id: str) -> bool:
        return self._lock_manager.is_locked("slack_connections", connection_id)

    def start_heartbeat(self, connection_id: str, job_id: str, lease_seconds: int = 900) -> None:
        self._lock_manager.start_heartbeat("slack_connections", connection_id, job_id, lease_seconds)

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
                    item_id = item.get("message_id") or item.get("id") or item.get("name")
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
                    count = self._db.slack_synced_messages.count_documents(
                        {"tenant_id": tenant_id, "connection_id": connection_id, "message_id": message_id},
                        limit=1
                    )
                    return count > 0
                except Exception as err:
                    print(f"[SlackStore] Mongo check error: {err}")
            return False

    def record_synced_message(self, record: SyncedSlackMessageRecord) -> None:
        key = f"{record.tenant_id}:{record.connection_id}:{record.message_id}"
        with self._lock:
            self._synced_messages[key] = record
            if self._db is not None:
                try:
                    self._db.slack_synced_messages.update_one(
                        {"tenant_id": record.tenant_id, "connection_id": record.connection_id, "message_id": record.message_id},
                        {"$set": record.to_dict()},
                        upsert=True
                    )
                except Exception as err:
                    print(f"[SlackStore] Mongo record error: {err}")

    def count_synced_messages(self, tenant_id: str, connection_id: str) -> int:
        with self._lock:
            if self._db is not None:
                try:
                    return self._db.slack_synced_messages.count_documents(
                        {"tenant_id": tenant_id, "connection_id": connection_id}
                    )
                except Exception as err:
                    print(f"[SlackStore] Mongo count error: {err}")
            prefix = f"{tenant_id}:{connection_id}:"
            return sum(1 for k in self._synced_messages if k.startswith(prefix))

    def record_activity(self, activity: SlackSyncActivity) -> None:
        with self._lock:
            acts = self._activities.setdefault(activity.connection_id, [])
            for idx, existing in enumerate(acts):
                if existing.job_id == activity.job_id:
                    acts[idx] = activity
                    break
            else:
                acts.insert(0, activity)

            if len(acts) > 50:
                self._activities[activity.connection_id] = acts[:50]

            if self._db is not None:
                try:
                    self._db.slack_sync_activities.update_one(
                        {"activity_id": activity.activity_id},
                        {"$set": activity.to_dict()},
                        upsert=True
                    )
                except Exception as err:
                    print(f"[SlackStore] Mongo activity error: {err}")

    def get_activities(self, connection_id: str, limit: int = 20) -> list[SlackSyncActivity]:
        with self._lock:
            if self._db is not None:
                try:
                    cursor = self._db.slack_sync_activities.find(
                        {"connection_id": connection_id}
                    ).sort("started_at", -1).limit(limit)
                    return [self._doc_to_activity(d) for d in cursor]
                except Exception as err:
                    print(f"[SlackStore] Mongo get activities error: {err}")
            return self._activities.get(connection_id, [])[:limit]

    def list_all_active_connections(self) -> list[SlackConnection]:
        with self._lock:
            if self._db is not None:
                try:
                    cursor = self._db.slack_connections.find({
                        "status": {"$in": [
                            SlackSyncStatus.CONNECTED.value,
                            SlackSyncStatus.SYNCING.value,
                            SlackSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC.value,
                            SlackSyncStatus.UP_TO_DATE.value,
                            SlackSyncStatus.PARTIAL_SUCCESS.value,
                        ]}
                    })
                    conns = [self._doc_to_connection(d) for d in cursor]
                    for c in conns:
                        self._connections[c.connection_id] = c
                    return conns
                except Exception as err:
                    print(f"[SlackStore] Mongo list error: {err}")

            return [
                c for c in self._connections.values()
                if c.status in (
                    SlackSyncStatus.CONNECTED,
                    SlackSyncStatus.SYNCING,
                    SlackSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC,
                    SlackSyncStatus.UP_TO_DATE,
                    SlackSyncStatus.PARTIAL_SUCCESS,
                )
            ]

    def purge_connection_data(self, tenant_id: str, connection_id: str) -> dict[str, int]:
        with self._lock:
            msgs_deleted = 0
            acts_deleted = 0

            # 1. Purge from MongoDB
            if self._db is not None:
                try:
                    res_msgs = self._db.slack_synced_messages.delete_many(
                        {"tenant_id": tenant_id, "connection_id": connection_id}
                    )
                    msgs_deleted = res_msgs.deleted_count

                    res_acts = self._db.slack_sync_activities.delete_many(
                        {"connection_id": connection_id}
                    )
                    acts_deleted = res_acts.deleted_count
                except Exception as err:
                    print(f"[SlackStore] Mongo purge error: {err}")

            # 2. Purge from in-memory
            prefix = f"{tenant_id}:{connection_id}:"
            keys_to_del = [k for k in self._synced_messages if k.startswith(prefix)]
            for k in keys_to_del:
                del self._synced_messages[k]
            if not msgs_deleted:
                msgs_deleted = len(keys_to_del)

            if connection_id in self._activities:
                if not acts_deleted:
                    acts_deleted = len(self._activities[connection_id])
                del self._activities[connection_id]

            # 3. Reset connection backfill counters
            conn = self._connections.get(connection_id)
            if conn:
                conn.backfill_state = SlackBackfillState()
                conn.current_progress = ""
                conn.last_successful_sync_at = None
                conn.status = SlackSyncStatus.CONFIGURATION_REQUIRED
                self.update_connection(conn)

            return {
                "synced_messages_deleted": msgs_deleted,
                "activities_deleted": acts_deleted,
            }

    @staticmethod
    def _doc_to_connection(doc: dict[str, Any]) -> SlackConnection:
        status_val = doc.get("status", SlackSyncStatus.AVAILABLE.value)
        try:
            status = SlackSyncStatus(status_val)
        except Exception:
            status = SlackSyncStatus.AVAILABLE

        config = SlackSyncConfig.from_dict(doc.get("config", {}))
        backfill_state = SlackBackfillState.from_dict(doc.get("backfill_state", {}))
        lock = SlackLockState.from_dict(doc.get("lock", {}))

        last_sync = None
        if doc.get("last_successful_sync_at"):
            try:
                last_sync = datetime.fromisoformat(doc["last_successful_sync_at"])
            except Exception:
                pass

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

        return SlackConnection(
            connection_id=doc.get("connection_id", ""),
            tenant_id=doc.get("tenant_id", "tenant_default"),
            user_id=doc.get("user_id", ""),
            account_name=doc.get("account_name", ""),
            status=status,
            config=config,
            backfill_state=backfill_state,
            lock=lock,
            current_progress=doc.get("current_progress", ""),
            webhook_trigger_id=doc.get("webhook_trigger_id"),
            last_successful_sync_at=last_sync,
            created_at=created_at,
            updated_at=updated_at,
        )

    @staticmethod
    def _doc_to_activity(doc: dict[str, Any]) -> SlackSyncActivity:
        trig_val = doc.get("trigger_type", SlackTriggerType.AUTO_SYNC.value)
        try:
            trigger_type = SlackTriggerType(trig_val)
        except Exception:
            trigger_type = SlackTriggerType.AUTO_SYNC

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

        return SlackSyncActivity(
            activity_id=doc.get("activity_id", ""),
            job_id=doc.get("job_id", ""),
            connection_id=doc.get("connection_id", ""),
            tenant_id=doc.get("tenant_id", "tenant_default"),
            trigger_type=trigger_type,
            status=doc.get("status", "COMPLETED"),
            started_at=started_at,
            completed_at=completed_at,
            metrics=doc.get("metrics", {}),
            items=doc.get("items", []),
        )
