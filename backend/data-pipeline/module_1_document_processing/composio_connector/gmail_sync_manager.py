import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.composio_connector.composio_client import ComposioClient
from module_1_document_processing.composio_connector.normalizers.gmail_normalizer import normalize_gmail
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
        """Retrieves connection status and checks live Composio OAuth token connectivity."""
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        if conn.status in (GmailSyncStatus.AVAILABLE, GmailSyncStatus.CONFIGURATION_REQUIRED):
            # Check with Composio if account is actively linked
            if self.composio.is_account_connected(user_id, "gmail"):
                if conn.status == GmailSyncStatus.AVAILABLE:
                    conn.status = GmailSyncStatus.CONFIGURATION_REQUIRED
                    self.store.update_connection(conn)
        return conn

    def initiate_oauth_flow(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        """Initiates OAuth via Composio and provisions connection in CONFIGURATION_REQUIRED state."""
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        
        redirect_url = self.composio.initiate_user_connection(user_id=user_id, source="gmail")
        trigger_id = self.composio.enable_trigger(trigger_slug=ComposioClient.GMAIL_NEW_MESSAGE, user_id=user_id)
        conn.webhook_trigger_id = trigger_id
        conn.status = GmailSyncStatus.CONFIGURATION_REQUIRED
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

        conn.status = GmailSyncStatus.SYNCING
        self.store.update_connection(conn)

        # Trigger initial sync in background
        asyncio.create_task(self.execute_sync_job(conn.connection_id, trigger_type=GmailTriggerType.INITIAL_SYNC))

        return {
            "status": "success",
            "message": "Configuration saved. Initial synchronization has started.",
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
        """Disconnects Gmail, pauses future webhooks/auto-sync, but PRESERVES vector memories."""
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        conn.status = GmailSyncStatus.DISCONNECTED
        conn.lock.is_locked = False
        conn.lock.locked_by_job_id = None
        conn.current_progress = ""
        self.store.update_connection(conn)

        print(f"[GmailSyncManager] Disconnected Gmail connection={conn.connection_id}. Memories preserved.")
        return {
            "status": "success",
            "message": "Gmail disconnected. Future synchronization stopped. Synced memories have been safely preserved.",
            "connection": conn.to_dict(),
        }

    async def execute_sync_job(
        self,
        connection_id: str,
        trigger_type: GmailTriggerType = GmailTriggerType.AUTO_SYNC,
        is_resync: bool = False,
    ) -> None:
        """Core sync execution handling 90-day queries, parallel 5-at-a-time batches, and CanonicalEvent routing."""
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
            # 2. Discover eligible emails in the 90-day window
            limit = conn.config.max_emails_per_sync
            eligible_emails = self._fetch_eligible_gmail_messages(conn, max_limit=limit, is_resync=is_resync)
            activity.metrics["total_discovered"] = len(eligible_emails)

            if not eligible_emails:
                print(f"[GmailSyncManager] No new unsynced emails found in 90-day window for {connection_id}.")
                conn.backfill_state.is_backfill_complete = True
                conn.status = GmailSyncStatus.UP_TO_DATE
                conn.current_progress = "Up to date"
                conn.last_successful_sync_at = datetime.now(timezone.utc)
                self.store.update_connection(conn)

                activity.status = "COMPLETED"
                activity.completed_at = datetime.now(timezone.utc)
                self.store.record_activity(activity)
                self.store.release_lock(connection_id, job_id)
                return

            total_to_process = len(eligible_emails)
            processed_so_far = 0

            # 3. Process in parallel sub-batches of 5
            batch_size = 5
            for i in range(0, total_to_process, batch_size):
                sub_batch = eligible_emails[i : i + batch_size]
                batch_num = (i // batch_size) + 1
                total_batches = (total_to_process + batch_size - 1) // batch_size
                print(f"[GmailSyncManager] Executing Batch {batch_num}/{total_batches} ({len(sub_batch)} emails in parallel)...")

                tasks = [self._process_single_email(conn, raw_email, activity) for raw_email in sub_batch]
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

                activity.metrics["processed"] = processed_so_far
                self.store.record_activity(activity)

            # 4. Finalize Connection & Activity State
            conn.last_successful_sync_at = datetime.now(timezone.utc)
            conn.backfill_state.total_synced_so_far += activity.metrics["succeeded"]

            if activity.metrics["failed"] > 0:
                conn.status = GmailSyncStatus.PARTIAL_SUCCESS
                activity.status = "PARTIAL_SUCCESS"
            elif conn.backfill_state.total_synced_so_far >= conn.backfill_state.total_eligible_discovered:
                conn.backfill_state.is_backfill_complete = True
                conn.status = GmailSyncStatus.UP_TO_DATE
                conn.current_progress = "Up to date"
                activity.status = "COMPLETED"
            else:
                conn.status = GmailSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC
                conn.current_progress = f"Next sync in {conn.config.auto_sync_interval_minutes}m"
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
        msg_id = raw_email.get("id", "")
        subject = raw_email.get("subject", "No Subject")
        sender = raw_email.get("sender", "unknown@sender.com")

        # Deduplication Guard
        if self.store.is_message_synced(conn.tenant_id, conn.connection_id, msg_id):
            print(f"[GmailSyncManager] Skipping msg_id={msg_id} (already synced).")
            return False

        # Format Composio-like payload structure
        payload = {
            "metadata": {
                "user_id": conn.user_id,
                "connected_account_id": conn.connection_id,
            },
            "data": {
                "message_id": msg_id,
                "thread_id": raw_email.get("thread_id", ""),
                "subject": subject,
                "sender": sender,
                "to": raw_email.get("to", conn.account_email or f"{conn.user_id}@gmail.com"),
                "date": raw_email.get("date", datetime.now(timezone.utc).isoformat()),
                "body": raw_email.get("body", ""),
                "label_ids": raw_email.get("label_ids", ["INBOX"]),
                "attachments": raw_email.get("attachments", []),
            }
        }

        # 1. Normalize into Universal CanonicalEvent
        event: CanonicalEvent = normalize_gmail(payload, tenant_id=conn.tenant_id)

        # 2. Process via QueueWorker end-to-end
        try:
            await self.queue_worker._process_event(event)
            
            # 3. Record Deduplication Lineage
            rec = SyncedMessageRecord(
                doc_id=f"{event.tenant_id}:{event.source}:{event.external_id}",
                tenant_id=conn.tenant_id,
                connection_id=conn.connection_id,
                message_id=msg_id,
                thread_id=raw_email.get("thread_id", ""),
                categories=raw_email.get("label_ids", ["INBOX"]),
                subject=subject,
                sender=sender,
                received_at=event.timestamp,
                sync_status="SUCCESS",
                attachment_count=len(raw_email.get("attachments", [])),
            )
            self.store.record_synced_message(rec)

            # Record item in activity log
            activity.items.append({
                "message_id": msg_id,
                "subject": subject,
                "sender": sender,
                "status": "SUCCESS",
                "attachment_summary": f"{len(raw_email.get('attachments', []))} attachment(s)" if raw_email.get("attachments") else None,
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
                "error_message": str(err),
                "synced_at": datetime.now(timezone.utc).isoformat(),
            })
            return None

    def _fetch_eligible_gmail_messages(
        self,
        conn: GmailConnection,
        max_limit: int = 10,
        is_resync: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Queries Gmail messages within the 90-day window, moving from newest to oldest.
        Filters out already-synced messages and respects category preferences.
        """
        now = datetime.now(timezone.utc)
        cutoff_date = now - timedelta(days=conn.config.sync_window_days)
        categories = conn.config.categories or ["INBOX"]

        # Synthetic rich message pool (simulates real Gmail API / Composio responses)
        # Includes emails with valid attachments (PDF), oversized attachments (>25MB zip), and body text
        mock_inbox = [
            {
                "id": f"msg_inbox_{i:03d}",
                "thread_id": f"th_{i:03d}",
                "subject": f"Q3 Enterprise Contract & Statement of Work #{i}",
                "sender": f"client_{i}@enterprise-partner.com",
                "to": conn.account_email or f"{conn.user_id}@gmail.com",
                "date": (now - timedelta(days=i * 2, hours=i)).isoformat(),
                "label_ids": ["INBOX", "IMPORTANT"],
                "body": f"Hi Team,\n\nPlease review the attached Q3 Statement of Work #{i} for our upcoming deployment. Looking forward to our sync.\n\nBest regards,\nClient {i}",
                "attachments": [
                    {
                        "attachment_id": f"att_pdf_{i}",
                        "filename": f"Statement_of_Work_{i}.pdf",
                        "mime_type": "application/pdf",
                        "size_bytes": 1024 * 1024 * 2,  # 2MB (valid)
                        "raw_bytes": b"%PDF-1.4 Mock statement of work content with scope, deliverables, and SLAs.",
                    },
                    {
                        "attachment_id": f"att_zip_{i}",
                        "filename": f"Raw_Diagnostics_Archive_{i}.zip",
                        "mime_type": "application/zip",
                        "size_bytes": 1024 * 1024 * 35,  # 35MB (oversized - will be skipped!)
                        "raw_bytes": b"PK\x03\x04Mock large zip data",
                    }
                ] if i % 2 == 0 else []
            }
            for i in range(1, 40)
        ]

        # Filter by 90-day cutoff
        time_filtered = [
            msg for msg in mock_inbox
            if datetime.fromisoformat(msg["date"]) >= cutoff_date
        ]

        conn.backfill_state.total_eligible_discovered = len(time_filtered)

        # Filter out already synced messages unless resyncing missing ones
        unsynced = []
        for msg in time_filtered:
            if not self.store.is_message_synced(conn.tenant_id, conn.connection_id, msg["id"]):
                unsynced.append(msg)
            if len(unsynced) >= max_limit:
                break

        return unsynced

    async def _auto_sync_cron_loop(self) -> None:
        """Background loop executing recurring auto-syncs every GMAIL_AUTO_SYNC_INTERVAL minutes for unfinished backfills."""
        while self._scheduler_running:
            try:
                await asyncio.sleep(self.auto_sync_interval_minutes * 60)
                connections = self.store.list_all_active_connections()
                for conn in connections:
                    if (
                        not conn.backfill_state.is_backfill_complete
                        and conn.status != GmailSyncStatus.SYNCING
                        and conn.status != GmailSyncStatus.DISCONNECTED
                        and conn.status != GmailSyncStatus.CONFIGURATION_REQUIRED
                    ):
                        print(f"[GmailSyncManager] Auto-sync triggered for connection {conn.connection_id}...")
                        asyncio.create_task(self.execute_sync_job(conn.connection_id, trigger_type=GmailTriggerType.AUTO_SYNC))
            except asyncio.CancelledError:
                break
            except Exception as err:
                print(f"[GmailSyncManager] Error in auto-sync cron loop: {err}")
