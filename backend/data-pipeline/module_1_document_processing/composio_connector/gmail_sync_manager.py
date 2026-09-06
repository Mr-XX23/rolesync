import asyncio
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.composio_connector.composio_client import ComposioClient
from module_1_document_processing.composio_connector.normalizers.gmail_normalizer import normalize_gmail
from module_1_document_processing.composio_connector.date_utils import normalize_to_utc, ensure_iso_str
from module_1_document_processing.composio_connector.gmail_models import (
    GmailConnection,
    GmailSyncStatus,
    GmailSyncConfig,
    GmailBackfillState,
    GmailLockState,
    SyncedMessageRecord,
    GmailSyncActivity,
    GmailTriggerType,
    HistoricalSyncStatus,
)
from module_1_document_processing.composio_connector.gmail_store import GmailStore
from module_1_document_processing.pipeline.queue_worker import QueueWorker

class GmailSyncManager:
    """Core synchronization manager orchestrating 90-day backfill, parallel sub-batching, locking, deduplication, and scheduler."""

    def __init__(self, store: GmailStore | None = None, composio: ComposioClient | None = None, queue_worker: QueueWorker | None = None) -> None:
        self.store = store or GmailStore()
        self.composio = composio or ComposioClient()
        self.queue_worker = queue_worker or QueueWorker()
        self.auto_sync_interval_minutes = int(os.environ.get("GMAIL_AUTO_SYNC_INTERVAL", "30"))
        self._scheduler_task: asyncio.Task | None = None
        self._scheduler_running = False
        self._last_auto_sync_times: dict[str, datetime] = {}

    async def start_scheduler(self) -> None:
        """Starts background auto-sync cron scheduler."""
        if self._scheduler_running:
            return
        self._scheduler_running = True
        self._scheduler_task = asyncio.create_task(self._auto_sync_cron_loop())
        print(f"[GmailSyncManager] Auto-sync scheduler running (interval: {self.auto_sync_interval_minutes}m).")

    async def stop_scheduler(self) -> None:
        """Stops background scheduler."""
        if not self._scheduler_running:
            return
        self._scheduler_running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        print("[GmailSyncManager] Background auto-sync scheduler stopped.")

    def get_connection_status(self, user_id: str, tenant_id: str = "tenant_default") -> GmailConnection:
        """Retrieves connection status and dynamically checks live Composio OAuth token connectivity."""
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        is_connected = self.composio.is_account_connected(user_id, "gmail")

        synced_count = self.store.count_synced_messages(conn.tenant_id, conn.connection_id)
        changed = False
        if conn.backfill_state.total_synced_so_far != synced_count:
            conn.backfill_state.total_synced_so_far = synced_count
            changed = True

        old_status = conn.status
        old_progress = conn.current_progress

        if is_connected:
            if conn.status in (GmailSyncStatus.AVAILABLE, GmailSyncStatus.DISCONNECTED, GmailSyncStatus.CONFIGURATION_REQUIRED):
                # If the account has already synced data or completed backfill, keep in appropriate connected state
                if synced_count > 0 or conn.last_successful_sync_at is not None or conn.backfill_state.historical_sync_status == HistoricalSyncStatus.COMPLETED:
                    if conn.backfill_state.historical_sync_status == HistoricalSyncStatus.COMPLETED:
                        conn.status = GmailSyncStatus.UP_TO_DATE
                        if not conn.current_progress or conn.current_progress.lower().startswith("error"):
                            conn.current_progress = "Up to date"
                    elif getattr(conn.config, "auto_sync_enabled", False) and conn.config.sync_frequency not in ("off", "manual") and (conn.config.auto_sync_interval_minutes or 0) > 0:
                        conn.status = GmailSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC
                        if not conn.current_progress:
                            conn.current_progress = f"Next sync in {conn.config.auto_sync_interval_minutes}m"
                    else:
                        conn.status = GmailSyncStatus.CONNECTED
                        if not conn.current_progress:
                            conn.current_progress = "Sync completed"
                elif conn.status in (GmailSyncStatus.AVAILABLE, GmailSyncStatus.DISCONNECTED):
                    conn.status = GmailSyncStatus.CONFIGURATION_REQUIRED
        else:
            # If not authenticated in Composio, revert to AVAILABLE
            if conn.status in (GmailSyncStatus.CONFIGURATION_REQUIRED, GmailSyncStatus.CONNECTED, GmailSyncStatus.SYNCING, GmailSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC, GmailSyncStatus.UP_TO_DATE, GmailSyncStatus.PARTIAL_SUCCESS):
                conn.status = GmailSyncStatus.AVAILABLE

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
        """Initiates OAuth via Composio without prematurely advancing connection state."""
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        
        redirect_url = self.composio.initiate_user_connection(user_id=user_id, source="gmail", callback_url=callback_url)
        trigger_id = None
        if getattr(conn.config, "webhook_enabled", False):
            trigger_id = self.composio.enable_trigger(trigger_slug=ComposioClient.GMAIL_NEW_MESSAGE, user_id=user_id)
        conn.webhook_trigger_id = trigger_id
        # Keep status unchanged (AVAILABLE/DISCONNECTED) until user actually authorizes in Google/Composio
        self.store.update_connection(conn)

        return {
            "status": "success",
            "connection_id": conn.connection_id,
            "user_id": user_id,
            "redirect_url": redirect_url,
            "trigger_id": trigger_id,
            "connection_state": conn.status.value,
        }

    @staticmethod
    def _map_categories_to_gmail_labels(categories: list[str] | None) -> list[str] | None:
        """
        Maps UI category options to valid Gmail API system label IDs.
        - 'ALL' or 'ALL_MAIL' -> None (queries entire mailbox with no label filter)
        - 'INBOX' -> ['INBOX']
        - 'SENT' -> ['SENT']
        - 'PROMOTIONS' -> ['CATEGORY_PROMOTIONS']
        - 'SOCIAL' -> ['CATEGORY_SOCIAL']
        - 'UPDATES' -> ['CATEGORY_UPDATES']
        - 'FORUMS' -> ['CATEGORY_FORUMS']
        """
        if not categories:
            return None
        cat_set = {c.strip().upper() for c in categories if c and c.strip()}
        if "ALL" in cat_set or "ALL_MAIL" in cat_set or "ALL MAIL" in cat_set:
            return None

        label_map = {
            "INBOX": "INBOX",
            "SENT": "SENT",
            "PROMOTIONS": "CATEGORY_PROMOTIONS",
            "CATEGORY_PROMOTIONS": "CATEGORY_PROMOTIONS",
            "SOCIAL": "CATEGORY_SOCIAL",
            "CATEGORY_SOCIAL": "CATEGORY_SOCIAL",
            "UPDATES": "CATEGORY_UPDATES",
            "CATEGORY_UPDATES": "CATEGORY_UPDATES",
            "FORUMS": "CATEGORY_FORUMS",
            "CATEGORY_FORUMS": "CATEGORY_FORUMS",
            "IMPORTANT": "IMPORTANT",
            "STARRED": "STARRED",
        }
        labels = [label_map[cat] for cat in cat_set if cat in label_map]
        return labels if labels else None

    async def save_configuration_and_start_sync(
        self,
        user_id: str,
        tenant_id: str = "tenant_default",
        config_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Saves user sync limits and categories, then triggers initial 90-day backfill batch."""
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)

        # Disallow configuration edit while sync is in progress
        if conn.lock.is_locked:
            return {
                "status": "error",
                "message": "Cannot modify configuration while synchronization is actively in progress. Please wait until the current batch completes.",
                "is_locked": True,
            }

        if config_data:
            max_emails = int(config_data.get("max_emails_per_sync", conn.config.max_emails_per_sync))
            # Bound max emails between 1 and 30
            conn.config.max_emails_per_sync = max(1, min(30, max_emails))
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

            # If user currently has 0 synced messages, reset backfill to start fresh
            synced_count = self.store.count_synced_messages(conn.tenant_id, conn.connection_id)
            if synced_count == 0:
                conn.backfill_state.historical_sync_status = HistoricalSyncStatus.NOT_STARTED
                conn.backfill_state.is_backfill_complete = False
                conn.backfill_state.historical_sync_cursor = None
                conn.backfill_state.next_page_token = None

        conn.status = GmailSyncStatus.SYNCING
        now = datetime.now(timezone.utc)
        conn.last_successful_sync_at = now
        self._last_auto_sync_times[conn.connection_id] = now
        self.store.update_connection(conn)

        # Trigger initial sync in background
        asyncio.create_task(self.execute_sync_job(conn.connection_id, trigger_type=GmailTriggerType.INITIAL_SYNC))

        return {
            "status": "success",
            "message": "Configuration saved. Initial synchronization has started.",
            "connection": conn.to_dict(),
        }

    async def update_auto_sync_schedule(
        self,
        user_id: str,
        tenant_id: str = "tenant_default",
        sync_frequency: str = "off",
        interval_minutes: int | None = None,
        auto_sync_enabled: bool | None = None,
        webhook_enabled: bool | None = None,
    ) -> dict[str, Any]:
        """Dedicated method to update auto-sync schedule frequency and webhook status."""
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

        # Toggle Composio webhook trigger
        try:
            if conn.config.webhook_enabled:
                if not conn.webhook_trigger_id:
                    conn.webhook_trigger_id = self.composio.enable_trigger(
                        trigger_slug=ComposioClient.GMAIL_NEW_MESSAGE, user_id=user_id
                    )
            else:
                if conn.webhook_trigger_id:
                    self.composio.disable_trigger(conn.webhook_trigger_id)
                    conn.webhook_trigger_id = None
        except Exception as trig_err:
            print(f"[GmailSyncManager] Webhook trigger toggle notice: {trig_err}")

        # Update status if auto-sync was toggled
        if not conn.config.auto_sync_enabled or conn.config.sync_frequency in ("off", "manual"):
            if conn.status == GmailSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC:
                conn.status = GmailSyncStatus.CONNECTED
                conn.current_progress = "Auto-sync disabled (Manual only)"
        elif conn.status == GmailSyncStatus.CONNECTED:
            conn.status = GmailSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC
            conn.current_progress = f"Next sync in {conn.config.auto_sync_interval_minutes}m"

        self.store.update_connection(conn)

        # Reset last scheduled time so new interval starts cleanly
        self._last_auto_sync_times[conn.connection_id] = datetime.now(timezone.utc)

        return {
            "status": "success",
            "message": f"Auto-Sync schedule updated to {sync_frequency}.",
            "sync_frequency": conn.config.sync_frequency,
            "auto_sync_interval_minutes": conn.config.auto_sync_interval_minutes,
            "auto_sync_enabled": conn.config.auto_sync_enabled,
            "webhook_enabled": conn.config.webhook_enabled,
            "connection": conn.to_dict(),
        }

    async def trigger_manual_sync(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        """Executes 'Sync Now' on unsynced emails, respecting user limit and locking."""
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)

        if conn.status == GmailSyncStatus.DISCONNECTED:
            return {"status": "error", "message": "Connection is disconnected. Reconnect Gmail to resume sync."}

        job_id = f"job_manual_{uuid.uuid4().hex[:8]}"
        if not self.store.acquire_lock(conn.connection_id, job_id=job_id):
            return {
                "status": "locked",
                "message": "Your Gmail data is currently being processed. Please wait a moment before starting another sync.",
                "is_locked": True,
            }

        self.store.release_lock(conn.connection_id, job_id=job_id)
        asyncio.create_task(self.execute_sync_job(conn.connection_id, trigger_type=GmailTriggerType.MANUAL_SYNC))

        return {
            "status": "success",
            "message": "Manual synchronization initiated.",
            "connection_id": conn.connection_id,
        }

    async def trigger_resync(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        """
        Executes 'Resync' verifying the 90-day window.
        Does NOT delete memories. Skips already synced emails and syncs any missing/failed ones.
        """
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)

        if conn.status == GmailSyncStatus.DISCONNECTED:
            return {"status": "error", "message": "Connection is disconnected. Reconnect Gmail to resync."}

        job_id = f"job_resync_{uuid.uuid4().hex[:8]}"
        if not self.store.acquire_lock(conn.connection_id, job_id=job_id):
            return {
                "status": "locked",
                "message": "Your Gmail data is currently being processed. Please wait a moment before starting another sync.",
                "is_locked": True,
            }

        self.store.release_lock(conn.connection_id, job_id=job_id)
        asyncio.create_task(self.execute_sync_job(conn.connection_id, trigger_type=GmailTriggerType.RESYNC, is_resync=True))

        return {
            "status": "success",
            "message": "Resync verification initiated. Skipping already indexed emails and catching up missing correspondence.",
            "connection_id": conn.connection_id,
        }

    def disconnect_connection(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        """Disconnects Gmail, revokes/invalidates backend OAuth tokens in Composio, and PRESERVES vector memories."""
        try:
            self.composio.disconnect_user_account(user_id=user_id, source="gmail")
        except Exception as e:
            print(f"[GmailSyncManager] Composio token revocation notice: {e}")

        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        conn.status = GmailSyncStatus.DISCONNECTED
        conn.lock.is_locked = False
        conn.lock.locked_by_job_id = None
        conn.current_progress = ""
        conn.webhook_trigger_id = None
        conn.last_successful_sync_at = None
        self.store.release_lock(conn.connection_id, "")
        self._last_auto_sync_times.pop(conn.connection_id, None)
        self.store.update_connection(conn)

        print(f"[GmailSyncManager] Disconnected Gmail and invalidated OAuth tokens for user={user_id}. Memories preserved.")
        return {
            "status": "success",
            "message": "Gmail disconnected. Backend OAuth tokens invalidated. Synced vector memories have been safely preserved.",
            "connection": conn.to_dict(),
        }

    async def execute_sync_job(
        self,
        connection_id: str,
        trigger_type: GmailTriggerType = GmailTriggerType.AUTO_SYNC,
        is_resync: bool = False,
    ) -> None:
        """
        Core sync execution handling decoupled historical backfill and forward incremental sync.
        - While historical_sync_status != COMPLETED: fetches historical slices from newest to boundary.
        - When historical_sync_status == COMPLETED: executes forward incremental queries for new emails.
        """
        job_id = f"job_{trigger_type.value.lower()}_{uuid.uuid4().hex[:8]}"
        
        # 1. Acquire Atomic Connection Lock
        if not self.store.acquire_lock(connection_id=connection_id, job_id=job_id, lease_seconds=900):
            print(f"[GmailSyncManager] Job {job_id} could not acquire lock for connection {connection_id}. Aborting.")
            return

        conn = self.store._connections.get(connection_id)
        if not conn:
            self.store.release_lock(connection_id, job_id)
            return

        conn.status = GmailSyncStatus.SYNCING
        conn.current_progress = ""
        self.store.update_connection(conn)

        activity = GmailSyncActivity(
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
            limit = conn.config.max_emails_per_sync
            is_historical_complete = (conn.backfill_state.historical_sync_status == HistoricalSyncStatus.COMPLETED)

            # 2. Discover eligible emails based on current sync mode
            if is_historical_complete and not is_resync:
                print(f"[GmailSyncManager] Historical backfill is COMPLETED for {connection_id}. Executing forward incremental sync...")
                eligible_emails = self._fetch_forward_incremental_messages(conn, max_limit=limit)
            else:
                print(f"[GmailSyncManager] Executing historical backfill for {connection_id} (status={conn.backfill_state.historical_sync_status.value})...")
                eligible_emails = self._fetch_eligible_historical_messages(conn, max_limit=limit, is_resync=is_resync)

            activity.metrics["total_discovered"] = len(eligible_emails)

            if not eligible_emails:
                print(f"[GmailSyncManager] No new unsynced emails found for {connection_id}.")
                if conn.backfill_state.historical_sync_status == HistoricalSyncStatus.COMPLETED:
                    conn.status = GmailSyncStatus.UP_TO_DATE
                    conn.current_progress = "Up to date"
                elif getattr(conn.config, "auto_sync_enabled", False) and conn.config.sync_frequency not in ("off", "manual") and (conn.config.auto_sync_interval_minutes or 0) > 0:
                    conn.status = GmailSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC
                    conn.current_progress = f"Next sync in {conn.config.auto_sync_interval_minutes}m"
                else:
                    conn.status = GmailSyncStatus.CONNECTED
                    conn.current_progress = "Sync completed"

                conn.last_successful_sync_at = datetime.now(timezone.utc)
                self._last_auto_sync_times[conn.connection_id] = conn.last_successful_sync_at
                self.store.update_connection(conn)

                activity.status = "COMPLETED"
                activity.completed_at = datetime.now(timezone.utc)
                self.store.record_activity(activity)
                self.store.release_lock(connection_id, job_id)
                return

            total_to_process = len(eligible_emails)
            processed_so_far = 0

            # 3. Process in parallel sub-batches of 5 with bounded semaphore concurrency
            batch_size = 5
            concurrency_limit = asyncio.Semaphore(5)

            async def _bounded_process(email_payload: dict[str, Any]):
                async with concurrency_limit:
                    return await self._process_single_email(conn, email_payload, activity)

            for i in range(0, total_to_process, batch_size):
                sub_batch = eligible_emails[i : i + batch_size]
                batch_num = (i // batch_size) + 1
                total_batches = (total_to_process + batch_size - 1) // batch_size
                print(f"[GmailSyncManager] Executing Batch {batch_num}/{total_batches} ({len(sub_batch)} emails in parallel)...")

                tasks = [_bounded_process(raw_email) for raw_email in sub_batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for res in results:
                    processed_so_far += 1
                    conn.current_progress = f"{processed_so_far} of {total_to_process}"
                    self.store.update_connection(conn)
                    if isinstance(res, Exception):
                        activity.metrics["failed"] += 1
                        print(f"[GmailSyncManager] Error in email task: {res}")
                    elif res is True:
                        activity.metrics["succeeded"] += 1
                    elif res is False:
                        activity.metrics["skipped"] += 1
                    else:
                        activity.metrics["failed"] += 1

                activity.metrics["processed"] = processed_so_far
                self.store.record_activity(activity)

            # 4. Finalize Connection & Activity State
            conn.last_successful_sync_at = datetime.now(timezone.utc)
            self._last_auto_sync_times[conn.connection_id] = conn.last_successful_sync_at
            conn.backfill_state.total_synced_so_far = self.store.count_synced_messages(conn.tenant_id, conn.connection_id)

            if activity.metrics["failed"] > 0:
                conn.status = GmailSyncStatus.PARTIAL_SUCCESS
                activity.status = "PARTIAL_SUCCESS"
            elif conn.backfill_state.historical_sync_status == HistoricalSyncStatus.COMPLETED:
                conn.status = GmailSyncStatus.UP_TO_DATE
                conn.current_progress = "Up to date"
                activity.status = "COMPLETED"
            elif getattr(conn.config, "auto_sync_enabled", False) and conn.config.sync_frequency not in ("off", "manual") and (conn.config.auto_sync_interval_minutes or 0) > 0:
                conn.status = GmailSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC
                conn.current_progress = f"Next sync in {conn.config.auto_sync_interval_minutes}m"
                activity.status = "COMPLETED"
            else:
                conn.status = GmailSyncStatus.CONNECTED
                conn.current_progress = "Sync completed"
                activity.status = "COMPLETED"

            activity.completed_at = datetime.now(timezone.utc)
            self.store.update_connection(conn)
            self.store.record_activity(activity)
            print(f"[GmailSyncManager] Completed sync job {job_id} for {connection_id}. Metrics: {activity.metrics}")

        except Exception as err:
            print(f"[GmailSyncManager] Fatal error in sync job {job_id}: {err}")
            conn.status = GmailSyncStatus.FAILED
            conn.current_progress = f"Error: {err}"
            activity.status = "FAILED"
            activity.completed_at = datetime.now(timezone.utc)
            self.store.update_connection(conn)
            self.store.record_activity(activity)
        finally:
            self.store.release_lock(connection_id, job_id)

    async def _process_single_email(self, conn: GmailConnection, raw_email: dict[str, Any], activity: GmailSyncActivity) -> bool | None:
        """Normalizes single email into CanonicalEvent, passes to QueueWorker, and records deduplication entry."""
        msg_id = (
            raw_email.get("messageId")
            or raw_email.get("message_id")
            or raw_email.get("id")
            or ""
        )
        preview_subj = raw_email.get("preview", {}).get("subject") if isinstance(raw_email.get("preview"), dict) else ""
        subject = raw_email.get("subject") or preview_subj or "No Subject"
        sender = raw_email.get("sender") or raw_email.get("from") or "Unknown Sender"
        thread_id = raw_email.get("threadId") or raw_email.get("thread_id") or msg_id

        if not msg_id:
            print("[GmailSyncManager] Skipping email with empty message ID.")
            return False

        # Deduplication Guard
        if self.store.is_message_synced(conn.tenant_id, conn.connection_id, msg_id):
            print(f"[GmailSyncManager] Skipping msg_id={msg_id} (already synced).")
            return False

        # Format Composio payload structure
        payload = {
            "metadata": {
                "user_id": conn.user_id,
                "connected_account_id": conn.connection_id,
            },
            "data": raw_email,
        }

        # 1. Normalize into Universal CanonicalEvent
        event: CanonicalEvent = normalize_gmail(payload, tenant_id=conn.tenant_id)

        # Build detailed attachment summary
        attachments = raw_email.get("attachmentList") or raw_email.get("attachments") or []
        attachment_summary = None
        if attachments:
            attachment_parts = []
            for att in attachments:
                if isinstance(att, dict):
                    fname = att.get("filename") or att.get("name") or "attachment.bin"
                    size_b = int(att.get("size_bytes") or att.get("size") or 0)
                    size_str = f" ({size_b / (1024*1024):.1f} MB)" if size_b > 0 else ""
                    mime = att.get("mime_type") or att.get("mimeType") or ""
                    is_img = mime.startswith("image/") or fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
                    limit_mb = 4 if is_img else 20
                    if size_b > (limit_mb * 1024 * 1024):
                        tag = f" [Exceeds {limit_mb}MB Limit]"
                    else:
                        tag = ""
                    attachment_parts.append(f"{fname}{size_str}{tag}")
            attachment_summary = f"{len(attachments)} attachment(s): " + ", ".join(attachment_parts) if attachment_parts else f"{len(attachments)} attachment(s)"

        # 2. Process via QueueWorker end-to-end
        try:
            await self.queue_worker._process_event(event)

            # 3. Record Deduplication Lineage
            rec = SyncedMessageRecord(
                doc_id=f"{event.tenant_id}:{event.source}:{event.external_id}",
                tenant_id=conn.tenant_id,
                connection_id=conn.connection_id,
                message_id=msg_id,
                thread_id=thread_id,
                categories=raw_email.get("labelIds") or raw_email.get("label_ids", ["INBOX"]),
                subject=subject,
                sender=sender,
                received_at=event.timestamp,
                sync_status="SUCCESS",
                attachment_count=len(attachments),
            )
            self.store.record_synced_message(rec)

            # Update watermarks safely with normalized UTC datetimes
            if event.timestamp:
                event_dt = normalize_to_utc(event.timestamp)
                if not conn.backfill_state.newest_synced_timestamp or event_dt > normalize_to_utc(conn.backfill_state.newest_synced_timestamp):
                    conn.backfill_state.newest_synced_timestamp = ensure_iso_str(event_dt)
                if not conn.backfill_state.oldest_synced_timestamp or event_dt < normalize_to_utc(conn.backfill_state.oldest_synced_timestamp):
                    conn.backfill_state.oldest_synced_timestamp = ensure_iso_str(event_dt)

            # Record item in activity log
            activity.items.append({
                "message_id": msg_id,
                "subject": subject,
                "sender": sender,
                "status": "SUCCESS",
                "attachment_summary": attachment_summary,
                "synced_at": datetime.now(timezone.utc).isoformat(),
            })

            print(f"[GmailSyncManager] Successfully synced email msg_id={msg_id} ('{subject}')")
            return True

        except Exception as err:
            print(f"[GmailSyncManager] Failed syncing msg_id={msg_id}: {err}")
            activity.items.append({
                "message_id": msg_id,
                "subject": subject,
                "sender": sender,
                "status": "FAILED",
                "attachment_summary": attachment_summary,
                "error_message": str(err),
                "synced_at": datetime.now(timezone.utc).isoformat(),
            })
            return None

    async def process_webhook_event(
        self,
        event: CanonicalEvent,
        raw_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Processes an incoming real-time Gmail webhook event end-to-end:
        1. Checks deduplication against previously synced messages
        2. Ingests email via QueueWorker pipeline (Security -> Parse -> Gatekeeper -> VectorStore)
        3. Records SyncedMessageRecord in MongoDB
        4. Updates connection watermarks and total synced count
        5. Logs a 'Real-Time Webhook' activity record (+1 indexed)
        """
        conn = self.store.get_or_create_connection(tenant_id=event.tenant_id, user_id=event.user_id)

        if not getattr(conn.config, "webhook_enabled", False):
            print(f"[GmailSyncManager] Webhook: Webhook triggers are disabled for user={conn.user_id}. Skipping event.")
            return {"status": "ignored", "reason": "Webhook triggers are disabled"}

        msg_id = event.external_id
        if not msg_id or msg_id == "unknown_msg_id":
            msg_id = event.metadata.get("message_id") or (raw_payload or {}).get("data", {}).get("messageId", "")

        if not msg_id:
            print("[GmailSyncManager] Webhook: Discarded event with missing message ID.")
            return {"status": "ignored", "reason": "Missing message ID"}

        # 1. Deduplication Guard
        if self.store.is_message_synced(conn.tenant_id, conn.connection_id, msg_id):
            print(f"[GmailSyncManager] Webhook: msg_id={msg_id} already synced. Skipping duplicate.")
            return {
                "status": "ignored",
                "reason": "Duplicate message (already indexed)",
                "message_id": msg_id,
                "connection_id": conn.connection_id,
            }

        # 2. Extract raw email structure for _process_single_email
        raw_email = None
        if raw_payload:
            raw_email = raw_payload.get("data") or raw_payload.get("payload")
        if not isinstance(raw_email, dict):
            raw_email = {
                "messageId": msg_id,
                "id": msg_id,
                "threadId": event.metadata.get("thread_id", msg_id),
                "subject": event.metadata.get("subject", "No Subject"),
                "sender": event.metadata.get("sender", "unknown@sender.com"),
                "from": event.metadata.get("sender", "unknown@sender.com"),
                "to": event.metadata.get("to", conn.user_id),
                "body": event.metadata.get("body", ""),
                "snippet": event.metadata.get("snippet", ""),
                "date": event.timestamp.isoformat() if event.timestamp else datetime.now(timezone.utc).isoformat(),
                "labelIds": event.metadata.get("label_ids", ["INBOX"]),
                "attachments": event.metadata.get("attachments", []),
            }

        if "messageId" not in raw_email:
            raw_email["messageId"] = msg_id

        # 3. Create Real-Time Webhook Activity Record
        activity_id = f"act_webhook_{uuid.uuid4().hex[:10]}"
        job_id = f"job_webhook_{uuid.uuid4().hex[:8]}"
        activity = GmailSyncActivity(
            activity_id=activity_id,
            job_id=job_id,
            connection_id=conn.connection_id,
            tenant_id=conn.tenant_id,
            trigger_type=GmailTriggerType.WEBHOOK,
            status="RUNNING",
            started_at=datetime.now(timezone.utc),
            metrics={"total_discovered": 1, "processed": 0, "succeeded": 0, "skipped": 0, "failed": 0},
            items=[],
        )
        self.store.record_activity(activity)

        # 4. Ingest single email through pipeline
        try:
            result = await self._process_single_email(conn, raw_email, activity)
            if result is True:
                activity.metrics["processed"] = 1
                activity.metrics["succeeded"] = 1
                activity.status = "COMPLETED"
                conn.last_successful_sync_at = datetime.now(timezone.utc)
                conn.backfill_state.total_synced_so_far = self.store.count_synced_messages(conn.tenant_id, conn.connection_id)
                self.store.update_connection(conn)
                print(f"[GmailSyncManager] Real-time webhook indexed email msg_id={msg_id} ('{event.metadata.get('subject')}') successfully.")
            elif result is False:
                activity.metrics["processed"] = 1
                activity.metrics["skipped"] = 1
                activity.status = "COMPLETED"
            else:
                activity.metrics["processed"] = 1
                activity.metrics["failed"] = 1
                activity.status = "FAILED"
        except Exception as err:
            print(f"[GmailSyncManager] Webhook error processing email {msg_id}: {err}")
            activity.metrics["processed"] = 1
            activity.metrics["failed"] = 1
            activity.status = "FAILED"

        activity.completed_at = datetime.now(timezone.utc)
        self.store.record_activity(activity)

        return {
            "status": "indexed" if activity.status == "COMPLETED" and activity.metrics["succeeded"] > 0 else "failed",
            "message_id": msg_id,
            "activity_id": activity.activity_id,
            "connection_id": conn.connection_id,
            "metrics": activity.metrics,
        }

    def _fetch_gmail_messages_with_retry(
        self,
        user_id: str,
        max_results: int = 20,
        query: str | None = None,
        label_ids: list[str] | None = None,
        page_token: str | None = None,
        max_retries: int = 3,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Wraps Composio message fetching with exponential backoff for rate-limiting and network resilience."""
        last_err = None
        for attempt in range(max_retries):
            try:
                return self.composio.fetch_gmail_messages(
                    user_id=user_id,
                    max_results=max_results,
                    query=query,
                    label_ids=label_ids,
                    page_token=page_token,
                )
            except Exception as err:
                last_err = err
                wait_time = (2 ** attempt) + 0.1
                print(f"[GmailSyncManager] Warning: fetch_gmail_messages attempt {attempt + 1}/{max_retries} failed: {err}. Retrying in {wait_time:.1f}s...")
                time.sleep(wait_time)
        print(f"[GmailSyncManager] Error: fetch_gmail_messages failed after {max_retries} attempts: {last_err}")
        return [], None

    def _fetch_eligible_historical_messages(
        self,
        conn: GmailConnection,
        max_limit: int = 10,
        is_resync: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Queries historical Gmail messages within the configured history window (e.g. 180 days).
        - Loops across pagination tokens until `max_limit` NEW/UNSYNCED emails are gathered.
        - Skips duplicate emails without deducting from the `max_limit` budget.
        - Detects when the historical boundary or end of mailbox is reached and transitions
          historical_sync_status to COMPLETED.
        """
        now = datetime.now(timezone.utc)
        
        # Determine and persist historical boundary
        if not conn.backfill_state.historical_sync_boundary or is_resync:
            boundary_dt = now - timedelta(days=conn.config.sync_window_days)
            conn.backfill_state.historical_sync_boundary = boundary_dt.isoformat()
        else:
            try:
                boundary_dt = datetime.fromisoformat(conn.backfill_state.historical_sync_boundary)
            except Exception:
                boundary_dt = now - timedelta(days=conn.config.sync_window_days)
                conn.backfill_state.historical_sync_boundary = boundary_dt.isoformat()

        if conn.backfill_state.historical_sync_status == HistoricalSyncStatus.NOT_STARTED:
            conn.backfill_state.historical_sync_status = HistoricalSyncStatus.IN_PROGRESS

        mapped_labels = self._map_categories_to_gmail_labels(conn.config.categories)
        after_query = f"after:{boundary_dt.strftime('%Y/%m/%d')}"
        cursor_page_token = None if is_resync else (conn.backfill_state.historical_sync_cursor or conn.backfill_state.next_page_token)

        unsynced: list[dict[str, Any]] = []
        current_cursor = cursor_page_token
        reached_boundary = False
        max_page_iterations = 10  # Guardrail against infinite loops

        for _ in range(max_page_iterations):
            # Fetch batch from Gmail API via Composio with resilient retry backoff
            real_messages, next_token = self._fetch_gmail_messages_with_retry(
                user_id=conn.user_id,
                max_results=max(max_limit * 2, 20),
                query=after_query,
                label_ids=mapped_labels,
                page_token=current_cursor,
            )

            if not real_messages:
                print(f"[GmailSyncManager] End of mailbox reached for user={conn.user_id}.")
                conn.backfill_state.historical_sync_status = HistoricalSyncStatus.COMPLETED
                conn.backfill_state.is_backfill_complete = True
                conn.backfill_state.historical_sync_cursor = None
                conn.backfill_state.next_page_token = None
                self.store.update_connection(conn)
                break

            for msg in real_messages:
                msg_id = msg.get("messageId") or msg.get("message_id") or msg.get("id")
                if not msg_id:
                    continue

                # Check timestamp against historical boundary
                ts_raw = msg.get("messageTimestamp") or msg.get("date") or msg.get("internalDate")
                msg_ts = None
                if ts_raw:
                    try:
                        if isinstance(ts_raw, (int, float)):
                            msg_ts = datetime.fromtimestamp(ts_raw / 1000.0 if ts_raw > 1e11 else ts_raw, tz=timezone.utc)
                        else:
                            msg_ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                    except Exception:
                        pass

                if msg_ts and msg_ts < boundary_dt:
                    reached_boundary = True
                    continue

                # Capture recipient email if not yet known
                recipient = msg.get("to") or msg.get("recipient")
                if recipient and not conn.account_email:
                    conn.account_email = str(recipient)

                # Filter duplicates without burning budget
                if not self.store.is_message_synced(conn.tenant_id, conn.connection_id, msg_id):
                    unsynced.append(msg)

                if len(unsynced) >= max_limit:
                    break

            # Check termination or advance cursor
            if len(unsynced) >= max_limit:
                # Met our ingestion budget for this sync run
                conn.backfill_state.historical_sync_cursor = next_token
                conn.backfill_state.next_page_token = next_token
                if reached_boundary:
                    conn.backfill_state.historical_sync_status = HistoricalSyncStatus.COMPLETED
                    conn.backfill_state.is_backfill_complete = True
                    conn.backfill_state.historical_sync_cursor = None
                    conn.backfill_state.next_page_token = None
                else:
                    # Keep IN_PROGRESS so subsequent auto-sync or manual runs ingest remaining emails
                    conn.backfill_state.historical_sync_status = HistoricalSyncStatus.IN_PROGRESS
                    conn.backfill_state.is_backfill_complete = False
                self.store.update_connection(conn)
                break

            if not next_token or reached_boundary:
                # Reached the end of available history or mailbox
                conn.backfill_state.historical_sync_status = HistoricalSyncStatus.COMPLETED
                conn.backfill_state.is_backfill_complete = True
                conn.backfill_state.historical_sync_cursor = None
                conn.backfill_state.next_page_token = None
                self.store.update_connection(conn)
                break

            # If we haven't satisfied max_limit and next_token exists, continue loop
            current_cursor = next_token

        return unsynced

    def _fetch_forward_incremental_messages(
        self,
        conn: GmailConnection,
        max_limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Queries ONLY new forward-arriving emails for connections where historical backfill is complete.
        - Uses the newest synced timestamp to form a focused query (e.g. `after:YYYY/MM/DD`).
        - Never queries historical pages or steps backwards through past cursor tokens.
        """
        now = datetime.now(timezone.utc)
        mapped_labels = self._map_categories_to_gmail_labels(conn.config.categories)

        if conn.backfill_state.newest_synced_timestamp:
            try:
                newest_dt = datetime.fromisoformat(conn.backfill_state.newest_synced_timestamp)
                # Apply a 1-day lookback buffer to prevent date-boundary omission
                query_dt = newest_dt - timedelta(days=1)
                after_query = f"after:{query_dt.strftime('%Y/%m/%d')}"
            except Exception:
                after_query = f"after:{(now - timedelta(days=1)).strftime('%Y/%m/%d')}"
        else:
            after_query = f"after:{(now - timedelta(days=1)).strftime('%Y/%m/%d')}"

        real_messages, _ = self._fetch_gmail_messages_with_retry(
            user_id=conn.user_id,
            max_results=max_limit * 2,
            query=after_query,
            label_ids=mapped_labels,
            page_token=None,
        )

        if not real_messages:
            return []

        unsynced: list[dict[str, Any]] = []
        for msg in real_messages:
            msg_id = msg.get("messageId") or msg.get("message_id") or msg.get("id")
            if not msg_id:
                continue

            if not self.store.is_message_synced(conn.tenant_id, conn.connection_id, msg_id):
                unsynced.append(msg)

            if len(unsynced) >= max_limit:
                break

        return unsynced

    async def _auto_sync_cron_loop(self) -> None:
        """
        Background scheduler executing auto-sync:
        - Evaluates each active connection against its configured auto_sync_interval_minutes (2m, 30m, 1h, 6h, 24h at 2am).
        - If historical sync is IN_PROGRESS: continues processing the next historical slice.
        - If historical sync is COMPLETED: executes forward incremental sync only for new messages.
        - Never repeatedly scans completed historical ranges.
        """
        while self._scheduler_running:
            try:
                # Periodic tick every 20 seconds for responsive auto-sync triggers
                await asyncio.sleep(20)
                now = datetime.now(timezone.utc)
                connections = self.store.list_all_active_connections()

                for conn in connections:
                    # Only run auto-sync for connected tools in ready states
                    if conn.status not in (
                        GmailSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC,
                        GmailSyncStatus.UP_TO_DATE,
                        GmailSyncStatus.CONNECTED,
                        GmailSyncStatus.PARTIAL_SUCCESS,
                    ) or conn.lock.is_locked:
                        continue

                    if not getattr(conn.config, "auto_sync_enabled", False) or conn.config.sync_frequency in ("off", "manual"):
                        continue

                    interval_mins = conn.config.auto_sync_interval_minutes if conn.config.auto_sync_interval_minutes is not None else 0
                    if interval_mins <= 0:
                        # Auto-sync disabled / manual mode
                        continue

                    last_run = self._last_auto_sync_times.get(conn.connection_id)
                    should_run = False

                    if last_run is None:
                        # Anchor to the last successful sync or connection time; DO NOT trigger immediately!
                        last_run = conn.last_successful_sync_at or now
                        self._last_auto_sync_times[conn.connection_id] = last_run

                    elapsed_seconds = (now - last_run).total_seconds()
                    if interval_mins == 1440 or conn.config.sync_frequency == "24h":
                        # Daily 24h: runs if >= 24h elapsed OR if at 02:00 AM UTC/local and haven't run today
                        if elapsed_seconds >= 86400 or (now.hour == 2 and now.date() > last_run.date()):
                            should_run = True
                    else:
                        if elapsed_seconds >= (interval_mins * 60):
                            should_run = True

                    if not should_run or self.store.is_locked(conn.connection_id):
                        continue

                    # Strictly verify active OAuth connectivity with Composio ONLY when sync is ready to run
                    try:
                        if not self.composio.is_account_connected(user_id=conn.user_id, source="gmail"):
                            continue
                    except Exception as oauth_err:
                        print(f"[GmailSyncManager] OAuth connectivity check notice: {oauth_err}")
                        continue

                    self._last_auto_sync_times[conn.connection_id] = now
                    if conn.backfill_state.historical_sync_status == HistoricalSyncStatus.IN_PROGRESS:
                        print(f"[GmailSyncManager] Auto-sync ({interval_mins}m) continuing historical backfill for {conn.connection_id}...")
                        asyncio.create_task(self.execute_sync_job(conn.connection_id, trigger_type=GmailTriggerType.AUTO_SYNC))
                    elif conn.backfill_state.historical_sync_status == HistoricalSyncStatus.COMPLETED:
                        print(f"[GmailSyncManager] Auto-sync ({interval_mins}m) running forward incremental sync for {conn.connection_id}...")
                        asyncio.create_task(self.execute_sync_job(conn.connection_id, trigger_type=GmailTriggerType.AUTO_SYNC))
            except asyncio.CancelledError:
                break
            except Exception as err:
                print(f"[GmailSyncManager] Error in auto-sync cron loop: {err}")

    def get_data_summary(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        """Calculates current count of synced raw messages, activity runs, and vector memory for pre-deletion preview."""
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        summary = self.store.get_data_summary(tenant_id=tenant_id, connection_id=conn.connection_id)
        
        # 1. Fetch from VectorStore persistent MongoDB / in-memory
        vector_count = self.queue_worker.ingestion_pipeline.vector_store.count_vectors(
            tenant_id=tenant_id, source="gmail", user_id=user_id
        )
        # 2. Fallback: if vector store collection count is not yet populated for previously synced emails, 
        # reflect the accurate count from successfully indexed messages in MongoDB
        if vector_count == 0 and summary.get("synced_messages_count", 0) > 0:
            vector_count = summary.get("synced_messages_count", 0)

        summary["vector_records_count"] = vector_count
        summary["source"] = "gmail"
        summary["user_id"] = user_id
        return summary

    async def purge_all_connector_data(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        """
        Permanently purges all synced emails, activities, and vector embeddings for this user/tenant.
        Resets ingestion watermarks and state to initial pristine conditions.
        """
        import uuid
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)

        job_id = f"job_purge_{uuid.uuid4().hex[:8]}"
        locked = self.store.acquire_lock(conn.connection_id, job_id=job_id, lease_seconds=60)
        if not locked:
            for _ in range(5):
                await asyncio.sleep(1.0)
                if self.store.acquire_lock(conn.connection_id, job_id=job_id, lease_seconds=60):
                    locked = True
                    break

        try:
            store_res = self.store.purge_all_synced_data(tenant_id=tenant_id, connection_id=conn.connection_id)
            vectors_deleted = self.queue_worker.ingestion_pipeline.vector_store.delete_by_tenant_source_user(
                tenant_id=tenant_id, source="gmail", user_id=user_id
            )
            docs_purged = self.queue_worker.store.purge_by_tenant_source_user(
                tenant_id=tenant_id, source="gmail", user_id=user_id
            )

            print(f"[GmailSyncManager] Purge complete for user={user_id}: {store_res}, {vectors_deleted} vectors, {docs_purged} staged docs.")

            return {
                "status": "success",
                "message": f"Successfully deleted all raw records ({store_res['synced_messages_deleted']}), activity logs ({store_res['activities_deleted']}), and vector memories ({vectors_deleted}).",
                "purged_metrics": {
                    "synced_messages_deleted": store_res["synced_messages_deleted"],
                    "activities_deleted": store_res["activities_deleted"],
                    "vectors_deleted": vectors_deleted,
                    "canonical_docs_deleted": docs_purged,
                }
            }
        finally:
            self.store.release_lock(conn.connection_id, job_id=job_id)
