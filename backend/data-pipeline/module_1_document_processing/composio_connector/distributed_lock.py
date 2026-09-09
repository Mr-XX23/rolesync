import asyncio
import os
import threading
from datetime import datetime, timezone, timedelta
from typing import Any

class DistributedLockManager:
    """
    Production-grade distributed atomic lock manager.
    - Uses MongoDB atomic CAS (find_one_and_update) when MongoDB is connected.
    - Falls back to re-entrant thread-safe in-memory locking when running locally or offline.
    - Provides background heartbeat lease extensions to prevent premature expiration on long-running sync jobs.
    - Automatically cleans up expired locks upon lease expiration.
    """

    def __init__(self, db: Any = None) -> None:
        self.db = db
        self._memory_locks: dict[str, dict[str, Any]] = {}
        self._thread_lock = threading.RLock()
        self._active_heartbeats: dict[str, asyncio.Task] = {}

    def set_db(self, db: Any) -> None:
        """Sets or updates the MongoDB database reference."""
        self.db = db

    def acquire_lock(
        self,
        collection_name: str,
        connection_id: str,
        job_id: str,
        lease_seconds: int = 900,
    ) -> bool:
        """
        Attempts to acquire an atomic lock for a given connection_id.
        Succeeds if:
        1. Lock is not locked, OR
        2. Lock has expired (expires_at < now), OR
        3. Lock is already held by the same job_id (re-entrant extension).
        """
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=lease_seconds)

        # 1. MongoDB Atomic CAS
        if self.db is not None:
            try:
                coll = self.db[collection_name]
                filter_q = {
                    "connection_id": connection_id,
                    "$or": [
                        {"lock.is_locked": False},
                        {"lock.expires_at": {"$lt": now}},
                        {"lock.locked_by_job_id": job_id},
                    ],
                }
                update_doc = {
                    "$set": {
                        "lock.is_locked": True,
                        "lock.locked_by_job_id": job_id,
                        "lock.locked_at": now,
                        "lock.expires_at": expires_at,
                        "updated_at": now,
                    }
                }
                res = coll.find_one_and_update(
                    filter=filter_q,
                    update=update_doc,
                    return_document=True,
                )
                if res:
                    with self._thread_lock:
                        self._memory_locks[connection_id] = {
                            "job_id": job_id,
                            "expires_at": expires_at,
                            "locked_at": now,
                        }
                    return True
                return False
            except Exception as err:
                print(f"[DistributedLockManager] MongoDB CAS lock check notice: {err}. Falling back to memory lock.")

        # 2. In-memory Thread-Safe Fallback
        with self._thread_lock:
            existing = self._memory_locks.get(connection_id)
            if existing:
                is_expired = existing["expires_at"] < now
                is_same_job = existing["job_id"] == job_id
                if not is_expired and not is_same_job:
                    return False

            self._memory_locks[connection_id] = {
                "job_id": job_id,
                "expires_at": expires_at,
                "locked_at": now,
            }
            return True

    def release_lock(
        self,
        collection_name: str,
        connection_id: str,
        job_id: str | None = None,
    ) -> bool:
        """Releases the lock for connection_id if held by job_id (or unconditionally if job_id is None)."""
        self.stop_heartbeat(connection_id)
        now = datetime.now(timezone.utc)

        # 1. MongoDB release
        if self.db is not None:
            try:
                coll = self.db[collection_name]
                filter_q: dict[str, Any] = {"connection_id": connection_id}
                if job_id:
                    filter_q["lock.locked_by_job_id"] = job_id

                coll.update_one(
                    filter_q,
                    {
                        "$set": {
                            "lock.is_locked": False,
                            "lock.locked_by_job_id": None,
                            "lock.locked_at": None,
                            "lock.expires_at": None,
                            "updated_at": now,
                        }
                    },
                )
            except Exception as err:
                print(f"[DistributedLockManager] MongoDB lock release notice: {err}")

        # 2. In-memory release
        with self._thread_lock:
            existing = self._memory_locks.get(connection_id)
            if existing:
                if job_id is None or existing.get("job_id") == job_id:
                    self._memory_locks.pop(connection_id, None)
                    return True
        return True

    def is_locked(self, collection_name: str, connection_id: str) -> bool:
        """Returns True if the connection is currently locked with an active non-expired lease."""
        now = datetime.now(timezone.utc)

        if self.db is not None:
            try:
                coll = self.db[collection_name]
                doc = coll.find_one(
                    {
                        "connection_id": connection_id,
                        "lock.is_locked": True,
                        "lock.expires_at": {"$gt": now},
                    },
                    {"lock": 1},
                )
                if doc:
                    return True
            except Exception:
                pass

        with self._thread_lock:
            existing = self._memory_locks.get(connection_id)
            if existing:
                return existing["expires_at"] > now
        return False

    def start_heartbeat(
        self,
        collection_name: str,
        connection_id: str,
        job_id: str,
        lease_seconds: int = 900,
        interval_seconds: int = 30,
    ) -> None:
        """Spawns an async heartbeat task that renews the lease expiration as long as the job is actively running."""
        self.stop_heartbeat(connection_id)

        async def _heartbeat_loop() -> None:
            while True:
                try:
                    await asyncio.sleep(interval_seconds)
                    now = datetime.now(timezone.utc)
                    expires_at = now + timedelta(seconds=lease_seconds)

                    if self.db is not None:
                        try:
                            self.db[collection_name].update_one(
                                {
                                    "connection_id": connection_id,
                                    "lock.locked_by_job_id": job_id,
                                },
                                {"$set": {"lock.expires_at": expires_at}},
                            )
                        except Exception:
                            pass

                    with self._thread_lock:
                        if connection_id in self._memory_locks and self._memory_locks[connection_id]["job_id"] == job_id:
                            self._memory_locks[connection_id]["expires_at"] = expires_at
                except asyncio.CancelledError:
                    break
                except Exception:
                    pass

        try:
            loop = asyncio.get_running_loop()
            self._active_heartbeats[connection_id] = loop.create_task(_heartbeat_loop())
        except RuntimeError:
            pass

    def stop_heartbeat(self, connection_id: str) -> None:
        """Stops the active heartbeat task for a connection."""
        task = self._active_heartbeats.pop(connection_id, None)
        if task and not task.done():
            task.cancel()
