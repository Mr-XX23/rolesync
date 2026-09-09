import asyncio
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.composio_connector.composio_client import ComposioClient
from module_1_document_processing.composio_connector.normalizers.notion_normalizer import normalize_notion
from module_1_document_processing.composio_connector.date_utils import normalize_to_utc
from module_1_document_processing.composio_connector.notion_models import (
    NotionConnection,
    NotionSyncStatus,
    NotionSyncConfig,
    NotionBackfillState,
    NotionLockState,
    SyncedNotionRecord,
    NotionSyncActivity,
    NotionActivityItem,
    NotionTriggerType,
    HistoricalSyncStatus,
)
from module_1_document_processing.composio_connector.notion_store import NotionStore
from module_1_document_processing.pipeline.queue_worker import QueueWorker
from module_1_document_processing.composio_connector.rate_limiter import global_rate_limiter
from module_1_document_processing.composio_connector.error_classifier import classify_error, ConnectorAction, ConnectorErrorType

class NotionSyncManager:
    """Core synchronization manager orchestrating Notion Pages, Databases, Blocks, Comments, Locking, and Scheduler."""

    def __init__(
        self,
        store: NotionStore | None = None,
        composio: ComposioClient | None = None,
        queue_worker: QueueWorker | None = None,
    ) -> None:
        self.store = store or NotionStore()
        self.composio = composio or ComposioClient()
        self.queue_worker = queue_worker or QueueWorker()
        self.auto_sync_interval_minutes = int(os.environ.get("NOTION_AUTO_SYNC_INTERVAL", "30"))
        self._scheduler_task: asyncio.Task | None = None
        self._scheduler_running = False
        self._last_auto_sync_times: dict[str, datetime] = {}

    async def start_scheduler(self) -> None:
        if self._scheduler_running:
            return
        self._scheduler_running = True
        self._scheduler_task = asyncio.create_task(self._auto_sync_cron_loop())
        print(f"[NotionSyncManager] Auto-sync scheduler running (interval: {self.auto_sync_interval_minutes}m).")

    async def stop_scheduler(self) -> None:
        if not self._scheduler_running:
            return
        self._scheduler_running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        print("[NotionSyncManager] Background auto-sync scheduler stopped.")

    def get_connection_status(self, user_id: str, tenant_id: str = "tenant_default") -> NotionConnection:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        is_connected = self.composio.is_account_connected(user_id, "notion")

        synced_count = self.store.count_synced_records(conn.tenant_id, conn.connection_id)
        changed = False
        if conn.backfill_state.total_synced_so_far != synced_count:
            conn.backfill_state.total_synced_so_far = synced_count
            changed = True

        old_status = conn.status
        old_progress = conn.current_progress

        if is_connected:
            if conn.status in (NotionSyncStatus.AVAILABLE, NotionSyncStatus.DISCONNECTED, NotionSyncStatus.CONFIGURATION_REQUIRED):
                if synced_count > 0 or conn.last_successful_sync_at is not None or conn.backfill_state.historical_sync_status == HistoricalSyncStatus.COMPLETED:
                    if conn.backfill_state.historical_sync_status == HistoricalSyncStatus.COMPLETED:
                        conn.status = NotionSyncStatus.UP_TO_DATE
                        if not conn.current_progress or conn.current_progress.lower().startswith("error"):
                            conn.current_progress = "Up to date"
                    elif getattr(conn.config, "auto_sync_enabled", False) and conn.config.sync_frequency not in ("off", "manual") and (conn.config.auto_sync_interval_minutes or 0) > 0:
                        conn.status = NotionSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC
                        if not conn.current_progress:
                            conn.current_progress = f"Next sync in {conn.config.auto_sync_interval_minutes}m"
                    else:
                        conn.status = NotionSyncStatus.CONNECTED
                        if not conn.current_progress:
                            conn.current_progress = "Sync completed"
                elif conn.status in (NotionSyncStatus.AVAILABLE, NotionSyncStatus.DISCONNECTED):
                    conn.status = NotionSyncStatus.CONFIGURATION_REQUIRED
        else:
            if conn.status in (NotionSyncStatus.CONFIGURATION_REQUIRED, NotionSyncStatus.CONNECTED, NotionSyncStatus.SYNCING, NotionSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC, NotionSyncStatus.UP_TO_DATE, NotionSyncStatus.PARTIAL_SUCCESS):
                conn.status = NotionSyncStatus.AVAILABLE

        if conn.status != old_status or conn.current_progress != old_progress:
            changed = True

        if changed:
            self.store.update_connection(conn)

        return conn

    def initiate_oauth_flow(
        self,
        user_id: str,
        tenant_id: str = "tenant_default",
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        redirect_url = self.composio.initiate_user_connection(user_id=user_id, source="notion", callback_url=callback_url)
        trigger_id = None
        if getattr(conn.config, "webhook_enabled", False):
            trigger_id = self.composio.enable_trigger(trigger_slug=ComposioClient.NOTION_PAGE_UPDATED, user_id=user_id)
        conn.webhook_trigger_id = trigger_id
        self.store.update_connection(conn)

        return {
            "status": "success",
            "connection_id": conn.connection_id,
            "user_id": user_id,
            "redirect_url": redirect_url,
            "trigger_id": trigger_id,
            "connection_state": conn.status.value,
        }

    async def save_configuration_and_start_sync(
        self,
        user_id: str,
        tenant_id: str = "tenant_default",
        config_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)

        if conn.lock.is_locked:
            return {
                "status": "error",
                "message": "Cannot modify configuration while Notion synchronization is actively in progress.",
                "is_locked": True,
            }

        if config_data:
            max_recs = int(config_data.get("max_records_per_sync", config_data.get("max_items_per_sync", conn.config.max_records_per_sync)))
            conn.config.max_records_per_sync = max(1, min(30, max_recs))
            if "categories" in config_data:
                conn.config.categories = [cat.upper() for cat in config_data["categories"] if cat]
            if "sync_window_days" in config_data:
                conn.config.sync_window_days = int(config_data["sync_window_days"])
            if "auto_sync_interval_minutes" in config_data:
                conn.config.auto_sync_interval_minutes = int(config_data["auto_sync_interval_minutes"])
            if "sync_frequency" in config_data:
                conn.config.sync_frequency = str(config_data["sync_frequency"])
            if "auto_sync_enabled" in config_data:
                conn.config.auto_sync_enabled = bool(config_data["auto_sync_enabled"])
            elif conn.config.sync_frequency in ("off", "manual"):
                conn.config.auto_sync_enabled = False
            if "webhook_enabled" in config_data:
                conn.config.webhook_enabled = bool(config_data["webhook_enabled"])

            synced_count = self.store.count_synced_records(conn.tenant_id, conn.connection_id)
            if synced_count == 0:
                conn.backfill_state.historical_sync_status = HistoricalSyncStatus.NOT_STARTED
                conn.backfill_state.is_backfill_complete = False
                conn.backfill_state.historical_sync_cursor = None
                conn.backfill_state.next_page_token = None

        conn.status = NotionSyncStatus.SYNCING
        now = datetime.now(timezone.utc)
        conn.last_successful_sync_at = now
        self._last_auto_sync_times[conn.connection_id] = now
        self.store.update_connection(conn)

        asyncio.create_task(self.execute_sync_job(conn.connection_id, trigger_type=NotionTriggerType.INITIAL_SYNC))

        return {
            "status": "success",
            "message": "Notion configuration saved. Initial synchronization has started.",
            "connection": conn.to_dict(),
        }

    def update_auto_sync_schedule(
        self,
        user_id: str,
        tenant_id: str = "tenant_default",
        sync_frequency: str = "off",
        interval_minutes: int | None = None,
        auto_sync_enabled: bool | None = None,
        webhook_enabled: bool | None = None,
    ) -> dict[str, Any]:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)

        freq_to_mins = {
            "off": 0,
            "2m": 2,
            "30m": 30,
            "1h": 60,
            "6h": 360,
            "24h": 1440,
            "realtime": 0,
            "manual": 0,
        }
        freq_lower = sync_frequency.lower().strip()
        if auto_sync_enabled is not None:
            conn.config.auto_sync_enabled = auto_sync_enabled
        elif freq_lower in ("off", "manual"):
            conn.config.auto_sync_enabled = False
        else:
            conn.config.auto_sync_enabled = True

        if webhook_enabled is not None:
            conn.config.webhook_enabled = webhook_enabled

        if interval_minutes is None:
            interval_minutes = freq_to_mins.get(freq_lower, 0 if not conn.config.auto_sync_enabled else 30)

        conn.config.auto_sync_interval_minutes = interval_minutes
        conn.config.sync_frequency = freq_lower

        try:
            if conn.config.webhook_enabled:
                if not conn.webhook_trigger_id or conn.webhook_trigger_id.startswith("trigger_"):
                    conn.webhook_trigger_id = self.composio.enable_trigger(
                        trigger_slug=ComposioClient.NOTION_PAGE_UPDATED, user_id=user_id
                    )
            else:
                if conn.webhook_trigger_id:
                    self.composio.disable_trigger(conn.webhook_trigger_id)
                    conn.webhook_trigger_id = None
        except Exception as trig_err:
            print(f"[NotionSyncManager] Webhook trigger toggle notice: {trig_err}")

        if not conn.config.auto_sync_enabled or conn.config.sync_frequency in ("off", "manual"):
            if conn.status == NotionSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC:
                conn.status = NotionSyncStatus.CONNECTED
                conn.current_progress = "Auto-sync disabled (Manual only)"
        elif conn.status == NotionSyncStatus.CONNECTED:
            conn.status = NotionSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC
            conn.current_progress = f"Next sync in {conn.config.auto_sync_interval_minutes}m"

        self.store.update_connection(conn)
        self._last_auto_sync_times[conn.connection_id] = datetime.now(timezone.utc)

        return {
            "status": "success",
            "message": f"Notion Auto-Sync schedule updated to {sync_frequency}.",
            "sync_frequency": conn.config.sync_frequency,
            "auto_sync_interval_minutes": conn.config.auto_sync_interval_minutes,
            "auto_sync_enabled": conn.config.auto_sync_enabled,
            "webhook_enabled": conn.config.webhook_enabled,
            "connection": conn.to_dict(),
        }

    async def trigger_manual_sync(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)

        if conn.status == NotionSyncStatus.DISCONNECTED:
            return {"status": "error", "message": "Connection is disconnected. Reconnect Notion to resume sync."}

        job_id = f"job_manual_{uuid.uuid4().hex[:8]}"
        if not self.store.acquire_lock(conn.connection_id, job_id=job_id):
            return {
                "status": "locked",
                "message": "Your Notion data is currently being processed. Please wait a moment before starting another sync.",
                "is_locked": True,
            }

        self.store.release_lock(conn.connection_id, job_id=job_id)
        asyncio.create_task(self.execute_sync_job(conn.connection_id, trigger_type=NotionTriggerType.MANUAL_SYNC))

        return {
            "status": "success",
            "message": "Notion manual synchronization initiated.",
            "connection_id": conn.connection_id,
        }

    async def trigger_resync(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)

        if conn.status == NotionSyncStatus.DISCONNECTED:
            return {"status": "error", "message": "Connection is disconnected. Reconnect Notion to resync."}

        job_id = f"job_resync_{uuid.uuid4().hex[:8]}"
        if not self.store.acquire_lock(conn.connection_id, job_id=job_id):
            return {
                "status": "locked",
                "message": "Your Notion data is currently being processed. Please wait a moment before starting another sync.",
                "is_locked": True,
            }

        self.store.release_lock(conn.connection_id, job_id=job_id)
        asyncio.create_task(self.execute_sync_job(conn.connection_id, trigger_type=NotionTriggerType.RESYNC, is_resync=True))

        return {
            "status": "success",
            "message": "Notion resync initiated. Skipping already indexed documents and syncing missing items.",
            "connection_id": conn.connection_id,
        }

    async def retry_failed_items(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        """Collects recently failed Notion items and triggers a targeted recovery sync."""
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        failed_items = self.store.get_failed_items(conn.connection_id)
        if not failed_items:
            return {
                "status": "success",
                "message": "No failed Notion records found to retry.",
                "retried_count": 0,
            }
        return await self.trigger_resync(user_id=user_id, tenant_id=tenant_id)

    def disconnect_connection(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        try:
            self.composio.disconnect_user_account(user_id=user_id, source="notion")
        except Exception as e:
            print(f"[NotionSyncManager] Composio token revocation notice: {e}")

        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        conn.status = NotionSyncStatus.DISCONNECTED
        conn.lock.is_locked = False
        conn.lock.locked_by_job_id = None
        conn.current_progress = ""
        conn.webhook_trigger_id = None
        conn.last_successful_sync_at = None
        self.store.release_lock(conn.connection_id, "")
        self._last_auto_sync_times.pop(conn.connection_id, None)
        self.store.update_connection(conn)

        print(f"[NotionSyncManager] Disconnected Notion for user={user_id}. Vector memories preserved.")
        return {
            "status": "success",
            "message": "Notion disconnected. Backend OAuth tokens invalidated. Synced vector memories preserved.",
            "connection": conn.to_dict(),
        }

    async def execute_sync_job(
        self,
        connection_id: str,
        trigger_type: NotionTriggerType = NotionTriggerType.AUTO_SYNC,
        is_resync: bool = False,
    ) -> None:
        job_id = f"job_{trigger_type.value.lower()}_{uuid.uuid4().hex[:8]}"

        if not self.store.acquire_lock(connection_id=connection_id, job_id=job_id, lease_seconds=900):
            print(f"[NotionSyncManager] Job {job_id} could not acquire lock for {connection_id}. Aborting.")
            return

        self.store.start_heartbeat(connection_id=connection_id, job_id=job_id, lease_seconds=900)

        conn = self.store._connections.get(connection_id)
        if not conn:
            self.store.stop_heartbeat(connection_id)
            self.store.release_lock(connection_id, job_id)
            return

        conn.status = NotionSyncStatus.SYNCING
        conn.current_progress = ""
        self.store.update_connection(conn)

        activity = NotionSyncActivity(
            activity_id=f"act_{job_id}",
            job_id=job_id,
            connection_id=connection_id,
            tenant_id=conn.tenant_id,
            trigger_type=trigger_type,
            status="RUNNING",
            started_at=datetime.now(timezone.utc),
            metrics={"total_discovered": 0, "processed": 0, "succeeded": 0, "skipped": 0, "failed": 0},
            items=[],
        )
        self.store.record_activity(activity)

        try:
            limit = conn.config.max_records_per_sync  # default 15, max 30

            # 1. Discover Notion items (pages, databases, blocks, comments)
            discovered_items = self._fetch_eligible_notion_items(conn, max_limit=limit, is_resync=is_resync)
            activity.metrics["total_discovered"] = len(discovered_items)

            if not discovered_items:
                print(f"[NotionSyncManager] No new unsynced records found for {connection_id}.")
                conn.status = NotionSyncStatus.UP_TO_DATE
                conn.current_progress = "Up to date"
                conn.last_successful_sync_at = datetime.now(timezone.utc)
                self._last_auto_sync_times[conn.connection_id] = conn.last_successful_sync_at
                self.store.update_connection(conn)

                activity.status = "COMPLETED"
                activity.completed_at = datetime.now(timezone.utc)
                self.store.record_activity(activity)
                self.store.release_lock(connection_id, job_id)
                return

            # 2. Parallel sub-batching 5 items at a time
            sub_batch_size = 5
            total_items = len(discovered_items)

            for i in range(0, total_items, sub_batch_size):
                sub_batch = discovered_items[i : i + sub_batch_size]
                tasks = [
                    self._process_single_notion_item(conn, item, is_resync=is_resync)
                    for item in sub_batch
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for r in results:
                    activity.metrics["processed"] += 1
                    if isinstance(r, Exception):
                        activity.metrics["failed"] += 1
                        activity.items.append({
                            "record_id": "unknown",
                            "name": "Processing error",
                            "subject": "Notion Processing Error",
                            "sender": "Notion (system)",
                            "object_type": "error",
                            "status": "FAILED",
                            "error_message": str(r),
                        })
                    elif isinstance(r, dict):
                        status = r.get("status", "FAILED")
                        if status in ("SUCCESS", "PARTIAL_SUCCESS"):
                            activity.metrics["succeeded"] += 1
                        elif status == "SKIPPED":
                            activity.metrics["skipped"] += 1
                        else:
                            activity.metrics["failed"] += 1
                        activity.items.append(r)

                processed = min(i + len(sub_batch), total_items)
                conn.current_progress = f"{processed} of {total_items}"
                self.store.update_connection(conn)
                self.store.record_activity(activity)

            # Finalize sync run
            conn.last_successful_sync_at = datetime.now(timezone.utc)
            self._last_auto_sync_times[conn.connection_id] = conn.last_successful_sync_at

            if activity.metrics["failed"] == 0:
                conn.status = NotionSyncStatus.UP_TO_DATE
                conn.current_progress = "Up to date"
                activity.status = "COMPLETED"
            elif activity.metrics["succeeded"] > 0:
                conn.status = NotionSyncStatus.PARTIAL_SUCCESS
                conn.current_progress = "Partial Success"
                activity.status = "PARTIAL_SUCCESS"
            else:
                conn.status = NotionSyncStatus.FAILED
                conn.current_progress = "Sync Failed"
                activity.status = "FAILED"

            activity.completed_at = datetime.now(timezone.utc)
            conn.backfill_state.total_synced_so_far = self.store.count_synced_records(conn.tenant_id, conn.connection_id)
            self.store.update_connection(conn)
            self.store.record_activity(activity)

        except Exception as e:
            err_type, sanitized_msg, action = classify_error(e)
            print(f"[NotionSyncManager] Error in sync job {job_id}: {sanitized_msg} (type={err_type})")
            if action == ConnectorAction.RECONNECT:
                conn.status = NotionSyncStatus.CONFIGURATION_REQUIRED
                conn.current_progress = "Access token expired. Reconnection required."
            else:
                conn.status = NotionSyncStatus.FAILED
                conn.current_progress = f"Error: {sanitized_msg[:120]}"
            self.store.update_connection(conn)
            activity.status = "FAILED"
            activity.completed_at = datetime.now(timezone.utc)
            self.store.record_activity(activity)
        finally:
            self.store.stop_heartbeat(connection_id)
            self.store.release_lock(connection_id, job_id)

    def _fetch_eligible_notion_items(
        self,
        conn: NotionConnection,
        max_limit: int = 15,
        is_resync: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Discovers Notion pages, databases, blocks, and comments via Composio tools.
        """
        user_id = conn.user_id
        if not self.composio or not getattr(self.composio, "_composio", None):
            print(f"[NotionSyncManager] Composio SDK not active. Returning empty list.")
            return []

        categories = conn.config.categories or ["PAGES", "DATABASES"]
        cat_set = {c.upper() for c in categories}
        include_all = "ALL" in cat_set

        collected_items: list[dict[str, Any]] = []

        # 1. Search pages and databases
        items = self._search_notion_workspace(user_id, limit=max_limit)
        for it in items:
            if len(collected_items) >= max_limit:
                break
            rec_id = it.get("id") or it.get("page_id") or it.get("database_id")
            if not rec_id:
                continue

            obj_type = (it.get("object") or "page").upper()
            if not include_all:
                if obj_type == "PAGE" and "PAGES" not in cat_set:
                    continue
                if obj_type == "DATABASE" and "DATABASES" not in cat_set:
                    continue

            if not is_resync and self.store.is_record_synced(conn.tenant_id, conn.connection_id, rec_id):
                continue

            collected_items.append(it)

        return collected_items[:max_limit]

    def _search_notion_workspace(self, user_id: str, limit: int = 15) -> list[dict[str, Any]]:
        """Searches Notion workspace pages and databases using Composio tools."""
        tool_slugs = ["NOTION_SEARCH_NOTION_PAGE"]
        for slug in tool_slugs:
            try:
                res = self.composio._composio.tools.execute(
                    slug=slug,
                    arguments={"page_size": min(limit, 30)},
                    user_id=user_id,
                    dangerously_skip_version_check=True,
                )
                data = res.get("data", {}) if isinstance(res, dict) else getattr(res, "data", {})
                if isinstance(data, dict):
                    results = data.get("results") or data.get("data", {}).get("results") or []
                    if results:
                        return results
            except Exception as e:
                print(f"[NotionSyncManager] Failed search via {slug}: {e}")
        return []

    async def _process_single_notion_item(
        self,
        conn: NotionConnection,
        item: dict[str, Any],
        is_resync: bool = False,
    ) -> dict[str, Any]:
        """Ingests a single Notion entity into the vector pipeline with deduplication and audit tracking."""
        rec_id = str(item.get("id") or item.get("page_id") or item.get("database_id") or "")
        obj_type = str(item.get("object") or "page").lower()
        title = item.get("title") or item.get("name") or f"Notion {obj_type.capitalize()} ({rec_id[:8]})"
        if isinstance(title, list):
            parts = [t.get("plain_text", "") for t in title if isinstance(t, dict)]
            title = "".join(parts) or f"Notion {obj_type.capitalize()}"

        if not is_resync and self.store.is_record_synced(conn.tenant_id, conn.connection_id, rec_id):
            return {
                "record_id": rec_id,
                "name": f"[{obj_type.upper()}] {str(title)[:60]}",
                "subject": str(title),
                "sender": f"Notion ({obj_type})",
                "object_type": obj_type,
                "status": "SKIPPED",
                "error_message": "Already indexed in vector memory",
                "url": item.get("url"),
            }

        await global_rate_limiter.acquire("notion")

        payload = {
            "metadata": {
                "user_id": conn.user_id,
                "entity_id": rec_id,
                "trigger_slug": f"NOTION_{obj_type.upper()}_UPDATED_TRIGGER",
            },
            "data": item,
        }
        canonical_event = normalize_notion(payload, tenant_id=conn.tenant_id)

        try:
            await self.queue_worker._process_event(canonical_event)

            rec = SyncedNotionRecord(
                doc_id=canonical_event.event_id,
                tenant_id=conn.tenant_id,
                connection_id=conn.connection_id,
                record_id=rec_id,
                object_type=obj_type,
                title=canonical_event.metadata.get("title", str(title)),
                url=canonical_event.metadata.get("url"),
                archived=canonical_event.metadata.get("archived", False),
                last_edited_time=canonical_event.timestamp,
                sync_status="SUCCESS",
                vector_chunk_count=1,
            )
            self.store.record_synced_record(rec)

            return {
                "record_id": rec_id,
                "name": f"[{obj_type.upper()}] {canonical_event.metadata.get('title', str(title))[:60]}",
                "subject": canonical_event.metadata.get("title", str(title)),
                "sender": f"Notion ({obj_type})",
                "object_type": obj_type,
                "status": "SUCCESS",
                "error_message": None,
                "url": canonical_event.metadata.get("url"),
            }
        except Exception as err:
            err_type, sanitized_err, _ = classify_error(err)
            return {
                "record_id": rec_id,
                "name": f"[{obj_type.upper()}] {str(title)[:60]}",
                "subject": str(title),
                "sender": f"Notion ({obj_type})",
                "object_type": obj_type,
                "status": "FAILED",
                "error_message": sanitized_err,
                "url": item.get("url"),
            }

    async def process_webhook_event(
        self,
        event: CanonicalEvent,
        raw_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Processes real-time Notion webhook events from Composio."""
        meta = (raw_payload or {}).get("metadata", {}) if isinstance(raw_payload, dict) else {}
        trigger_id = meta.get("trigger_id") or meta.get("trigger_slug") or (event.raw_ref or {}).get("trigger_id")

        conn = None
        # 1. Match by trigger_id if available
        if trigger_id:
            conn = self.store.find_connection_by_trigger_id(trigger_id)

        # 2. Check if event.user_id matches an existing connection
        if not conn and event.user_id:
            conn = self.store.get_connection(tenant_id=event.tenant_id, user_id=event.user_id)

        # 3. Match connection with webhook_enabled == True
        if not conn:
            conn = self.store.find_active_webhook_connection(tenant_id=event.tenant_id)
            if not conn:
                conn = self.store.find_active_webhook_connection(tenant_id=None)

        # 4. Fallback to any active connection
        if not conn:
            active_conns = self.store.list_all_active_connections()
            if active_conns:
                conn = active_conns[0]

        # 5. Last resort fallback
        if not conn:
            conn = self.store.get_or_create_connection(tenant_id=event.tenant_id, user_id=event.user_id or "usr_active")

        # Crucial: align event tenant and user with the matched connection
        event.tenant_id = conn.tenant_id
        event.user_id = conn.user_id

        rec_id = event.external_id
        if self.store.is_record_synced(event.tenant_id, conn.connection_id, rec_id):
            return {"status": "ignored", "reason": "Notion record already synced"}

        await self.queue_worker._process_event(event)

        obj_type = event.metadata.get("object_type", "page")
        title = event.metadata.get("title", "Untitled Document")

        rec = SyncedNotionRecord(
            doc_id=event.event_id,
            tenant_id=event.tenant_id,
            connection_id=conn.connection_id,
            record_id=rec_id,
            object_type=obj_type,
            title=title,
            url=event.metadata.get("url"),
            archived=event.metadata.get("archived", False),
            last_edited_time=event.timestamp,
            sync_status="SUCCESS",
            vector_chunk_count=1,
        )
        self.store.record_synced_record(rec)

        activity = NotionSyncActivity(
            activity_id=f"act_wh_{uuid.uuid4().hex[:8]}",
            job_id=f"job_wh_{uuid.uuid4().hex[:8]}",
            connection_id=conn.connection_id,
            tenant_id=conn.tenant_id,
            trigger_type=NotionTriggerType.WEBHOOK,
            status="COMPLETED",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            metrics={"total_discovered": 1, "processed": 1, "succeeded": 1, "skipped": 0, "failed": 0},
            items=[{
                "record_id": rec_id,
                "name": f"[{obj_type.upper()}] {title[:60]}",
                "subject": title,
                "sender": f"Notion ({obj_type})",
                "object_type": obj_type,
                "status": "SUCCESS",
                "error_message": None,
                "url": event.metadata.get("url"),
            }],
        )
        self.store.record_activity(activity)

        conn.last_successful_sync_at = datetime.now(timezone.utc)
        conn.backfill_state.total_synced_so_far = self.store.count_synced_records(conn.tenant_id, conn.connection_id)
        self.store.update_connection(conn)

        return {"status": "success", "event_id": event.event_id, "record_id": rec_id}

    def get_data_summary(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        synced_count = self.store.count_synced_records(tenant_id, conn.connection_id)
        acts = self.store.get_activities(conn.connection_id, limit=50)

        vector_count = 0
        try:
            vector_count = self.queue_worker.ingestion_pipeline.vector_store.count_vectors(
                tenant_id=tenant_id, source="notion", user_id=user_id
            )
        except Exception:
            vector_count = synced_count

        return {
            "tenant_id": tenant_id,
            "connection_id": conn.connection_id,
            "synced_messages_count": synced_count,
            "activities_count": len(acts),
            "vector_records_count": vector_count,
            "is_backfill_complete": conn.backfill_state.is_backfill_complete,
            "historical_status": conn.backfill_state.historical_sync_status.value,
        }

    async def purge_all_connector_data(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        conn_id = conn.connection_id

        purge_metrics = self.store.purge_connection_data(tenant_id=tenant_id, connection_id=conn_id)

        vectors_deleted = 0
        try:
            vectors_deleted = self.queue_worker.ingestion_pipeline.vector_store.delete_by_tenant_source_user(
                tenant_id=tenant_id, source="notion", user_id=user_id
            )
        except Exception as e:
            print(f"[NotionSyncManager] Vector deletion error: {e}")

        docs_purged = 0
        try:
            docs_purged = self.queue_worker.store.purge_by_tenant_source_user(
                tenant_id=tenant_id, source="notion", user_id=user_id
            )
        except Exception as e:
            print(f"[NotionSyncManager] Canonical docs purge error: {e}")

        conn.backfill_state = NotionBackfillState()
        conn.current_progress = ""
        conn.last_successful_sync_at = None
        conn.status = NotionSyncStatus.CONFIGURATION_REQUIRED
        self.store.update_connection(conn)

        return {
            "status": "success",
            "message": "Notion connector data, vector embeddings, deduplication state, and activity logs have been purged.",
            "purged_metrics": {
                "synced_messages_deleted": purge_metrics.get("synced_records_deleted", 0),
                "activities_deleted": purge_metrics.get("activities_deleted", 0),
                "vectors_deleted": vectors_deleted,
                "canonical_docs_deleted": docs_purged,
            },
        }

    async def _auto_sync_cron_loop(self) -> None:
        while self._scheduler_running:
            try:
                await asyncio.sleep(60)
                if not self._scheduler_running:
                    break

                now = datetime.now(timezone.utc)
                active_conns = self.store.list_all_active_connections()

                for conn in active_conns:
                    if not getattr(conn.config, "auto_sync_enabled", False):
                        continue
                    if conn.config.sync_frequency in ("off", "manual"):
                        continue
                    interval_mins = conn.config.auto_sync_interval_minutes or 30
                    if interval_mins <= 0:
                        continue

                    last_run = self._last_auto_sync_times.get(conn.connection_id) or conn.last_successful_sync_at
                    if not last_run or (now - last_run) >= timedelta(minutes=interval_mins):
                        if not self.store.is_locked(conn.connection_id):
                            print(f"[NotionSyncManager] Triggering scheduled auto-sync for {conn.connection_id} (interval={interval_mins}m)...")
                            self._last_auto_sync_times[conn.connection_id] = now
                            asyncio.create_task(
                                self.execute_sync_job(conn.connection_id, trigger_type=NotionTriggerType.AUTO_SYNC)
                            )
            except asyncio.CancelledError:
                break
            except Exception as loop_err:
                print(f"[NotionSyncManager] Scheduler loop notice: {loop_err}")
                await asyncio.sleep(10)
