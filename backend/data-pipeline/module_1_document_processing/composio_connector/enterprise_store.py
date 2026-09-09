import os
import threading
import logging
from datetime import datetime, timezone
import uuid

try:
    from pymongo import MongoClient, ASCENDING
except ImportError:
    MongoClient = None
    ASCENDING = 1

logger = logging.getLogger(__name__)


class EnterpriseStore:
    """MongoDB & In-Memory Store managing Enterprise custom connector pipeline requests."""

    def __init__(self) -> None:
        self.mongo_uri = os.environ.get("MONGODB_URI", "mongodb://mongodb:27017")
        self.db_name = os.environ.get("MONGODB_DB_NAME", "rolesync_rag")
        self._lock = threading.RLock()
        self._requests: dict[str, dict] = {}

        self._mongo_client = None
        self._db = None
        if MongoClient and self.mongo_uri:
            try:
                self._mongo_client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=1000)
                self._mongo_client.admin.command("ping")
                self._db = self._mongo_client[self.db_name]
                self._db.enterprise_sync_requests.create_index([("user_id", ASCENDING), ("created_at", -1)])
                self._db.enterprise_sync_requests.create_index([("request_id", ASCENDING)], unique=True)
                logger.info(f"[EnterpriseStore] Connected to MongoDB {self.mongo_uri}/{self.db_name}")
            except Exception as e:
                logger.warning(f"[EnterpriseStore] MongoDB offline or unreachable ({e}), using in-memory fallback.")
                self._mongo_client = None
                self._db = None

    def create_request(
        self,
        user_id: str,
        tenant_id: str,
        database_system: str,
        requirements: str,
        contact_email: str | None = None,
    ) -> dict:
        req_id = f"req_ent_{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "request_id": req_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "database_system": database_system.strip(),
            "requirements": requirements.strip(),
            "contact_email": contact_email or user_id,
            "status": "UNDER_REVIEW",
            "estimated_sla_hours": 24,
            "created_at": now,
            "updated_at": now,
        }

        with self._lock:
            self._requests[req_id] = record

        if self._db is not None:
            try:
                self._db.enterprise_sync_requests.insert_one(dict(record))
            except Exception as e:
                logger.error(f"[EnterpriseStore] Error saving enterprise request to mongo: {e}")

        record_copy = dict(record)
        record_copy.pop("_id", None)
        return record_copy

    def get_requests(self, user_id: str, tenant_id: str | None = None) -> list[dict]:
        results: list[dict] = []
        if self._db is not None:
            try:
                query: dict = {"user_id": user_id}
                if tenant_id and tenant_id != "tenant_default":
                    query["tenant_id"] = tenant_id
                cursor = self._db.enterprise_sync_requests.find(query).sort("created_at", -1)
                for doc in cursor:
                    doc.pop("_id", None)
                    results.append(doc)
                if results:
                    return results
            except Exception as e:
                logger.error(f"[EnterpriseStore] Error fetching requests from mongo: {e}")

        with self._lock:
            for r in self._requests.values():
                if r.get("user_id") == user_id:
                    if not tenant_id or tenant_id == "tenant_default" or r.get("tenant_id") == tenant_id:
                        r_copy = dict(r)
                        r_copy.pop("_id", None)
                        results.append(r_copy)

        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results

    def cancel_request(self, request_id: str, user_id: str) -> bool:
        with self._lock:
            if request_id in self._requests:
                del self._requests[request_id]

        if self._db is not None:
            try:
                res = self._db.enterprise_sync_requests.delete_one({"request_id": request_id, "user_id": user_id})
                return res.deleted_count > 0
            except Exception as e:
                logger.error(f"[EnterpriseStore] Error deleting request {request_id}: {e}")
        return True
