import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from module_1_document_processing.composio_connector.composio_client import ComposioClient
from module_1_document_processing.composio_connector.gdrive_models import (
    GDriveConnection,
    GDriveSyncConfig,
    GDriveBackfillState,
    GDriveSyncStatus,
    GDriveTriggerType,
    HistoricalSyncStatus,
    SyncedFileRecord,
    GDriveSyncActivity,
)
from module_1_document_processing.composio_connector.gdrive_store import GDriveStore
from module_1_document_processing.composio_connector.normalizers.gdrive_normalizer import normalize_gdrive
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.composio_connector.date_utils import normalize_to_utc, ensure_iso_str
from module_1_document_processing.pipeline.queue_worker import QueueWorker

class GDriveSyncManager:
    """Production Sync Manager orchestrating Google Drive OAuth, pagination, LlamaParse file ingestion, auto-sync, and real-time webhooks."""

    def __init__(
        self,
        composio_client: ComposioClient | None = None,
        store: GDriveStore | None = None,
        queue_worker: QueueWorker | None = None,
    ) -> None:
        self.composio = composio_client or ComposioClient()
        self.store = store or GDriveStore()
        self.queue_worker = queue_worker or QueueWorker()

        self._scheduler_task: asyncio.Task | None = None
        self._is_scheduler_running = False
        self.auto_sync_interval_minutes = 30
        self._last_auto_sync_times: dict[str, datetime] = {}

    async def start_scheduler(self) -> None:
        if self._is_scheduler_running:
            return
        self._is_scheduler_running = True
        self._scheduler_task = asyncio.create_task(self._auto_sync_loop())
        print(f"[GDriveSyncManager] Auto-sync scheduler running (interval: {self.auto_sync_interval_minutes}m).")

    async def stop_scheduler(self) -> None:
        if not self._is_scheduler_running:
            return
        self._is_scheduler_running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        print("[GDriveSyncManager] Background auto-sync scheduler stopped.")

    def get_connection_status(self, user_id: str, tenant_id: str = "tenant_default") -> GDriveConnection:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        is_authenticated = self.composio.is_account_connected(user_id=user_id, source="gdrive")

        synced_count = self.store.count_synced_files(conn.tenant_id, conn.connection_id)
        changed = False
        if conn.backfill_state.total_synced_so_far != synced_count:
            conn.backfill_state.total_synced_so_far = synced_count
            changed = True

        old_status = conn.status
        old_progress = conn.current_progress

        if is_authenticated:
            if conn.status in (GDriveSyncStatus.AVAILABLE, GDriveSyncStatus.DISCONNECTED, GDriveSyncStatus.CONFIGURATION_REQUIRED):
                if synced_count > 0 or conn.last_successful_sync_at is not None or conn.backfill_state.historical_sync_status == HistoricalSyncStatus.COMPLETED:
                    if conn.backfill_state.historical_sync_status == HistoricalSyncStatus.COMPLETED:
                        conn.status = GDriveSyncStatus.UP_TO_DATE
                        if not conn.current_progress or conn.current_progress.lower().startswith("error"):
                            conn.current_progress = "Up to date"
                    elif getattr(conn.config, "auto_sync_enabled", False) and conn.config.sync_frequency not in ("off", "manual") and (conn.config.auto_sync_interval_minutes or 0) > 0:
                        conn.status = GDriveSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC
                        if not conn.current_progress:
                            conn.current_progress = f"Next sync in {conn.config.auto_sync_interval_minutes}m"
                    else:
                        conn.status = GDriveSyncStatus.CONNECTED
                        if not conn.current_progress:
                            conn.current_progress = "Sync completed"
                else:
                    conn.status = GDriveSyncStatus.CONFIGURATION_REQUIRED
        else:
            if conn.status in (
                GDriveSyncStatus.CONFIGURATION_REQUIRED,
                GDriveSyncStatus.CONNECTED,
                GDriveSyncStatus.SYNCING,
                GDriveSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC,
                GDriveSyncStatus.UP_TO_DATE,
                GDriveSyncStatus.PARTIAL_SUCCESS,
            ):
                conn.status = GDriveSyncStatus.AVAILABLE

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
        redirect_url = self.composio.initiate_user_connection(user_id=user_id, source="gdrive", callback_url=callback_url)
        trigger_id = None
        if getattr(conn.config, "webhook_enabled", False):
            trigger_id = self.composio.enable_trigger(trigger_slug=ComposioClient.GDRIVE_FILE_CREATED, user_id=user_id)
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
        config: GDriveSyncConfig | None = None,
    ) -> dict[str, Any]:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        if config:
            conn.config = config

        now = datetime.now(timezone.utc)
        conn.last_successful_sync_at = now
        self._last_auto_sync_times[conn.connection_id] = now

        conn.status = GDriveSyncStatus.SYNCING
        conn.current_progress = f"Starting initial Google Drive sync..."
        self.store.update_connection(conn)

        # Launch non-blocking sync job in background safely
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.start_sync_job(conn.connection_id, trigger_type=GDriveTriggerType.INITIAL_SYNC))
        except RuntimeError:
            import threading
            threading.Thread(
                target=lambda: asyncio.run(self.start_sync_job(conn.connection_id, trigger_type=GDriveTriggerType.INITIAL_SYNC)),
                daemon=True,
            ).start()

        return {
            "status": "success",
            "message": "Google Drive synchronization initiated.",
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
        freq = sync_frequency.lower().strip()
        conn.config.sync_frequency = freq

        if auto_sync_enabled is not None:
            conn.config.auto_sync_enabled = auto_sync_enabled
        elif freq in ("off", "manual"):
            conn.config.auto_sync_enabled = False
        else:
            conn.config.auto_sync_enabled = True

        if webhook_enabled is not None:
            conn.config.webhook_enabled = webhook_enabled

        if interval_minutes and interval_minutes > 0:
            conn.config.auto_sync_interval_minutes = interval_minutes
        elif freq == "2m":
            conn.config.auto_sync_interval_minutes = 2
        elif freq == "30m":
            conn.config.auto_sync_interval_minutes = 30
        elif freq in ("1h", "60m"):
            conn.config.auto_sync_interval_minutes = 60
        elif freq in ("6h", "360m"):
            conn.config.auto_sync_interval_minutes = 360
        elif freq in ("24h", "1440m"):
            conn.config.auto_sync_interval_minutes = 1440
        else:
            conn.config.auto_sync_interval_minutes = 0

        # Toggle Composio webhook trigger
        try:
            if conn.config.webhook_enabled:
                if not conn.webhook_trigger_id:
                    conn.webhook_trigger_id = self.composio.enable_trigger(
                        trigger_slug=ComposioClient.GDRIVE_FILE_CREATED, user_id=user_id
                    )
            else:
                if conn.webhook_trigger_id:
                    self.composio.disable_trigger(conn.webhook_trigger_id)
                    conn.webhook_trigger_id = None
        except Exception as trig_err:
            print(f"[GDriveSyncManager] Webhook trigger toggle notice: {trig_err}")

        if not conn.config.auto_sync_enabled or freq in ("off", "manual"):
            if conn.status == GDriveSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC:
                conn.status = GDriveSyncStatus.CONNECTED
                conn.current_progress = "Auto-sync disabled (Manual only)"
        elif conn.status == GDriveSyncStatus.CONNECTED:
            conn.status = GDriveSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC
            conn.current_progress = f"Next sync in {conn.config.auto_sync_interval_minutes}m"

        self._last_auto_sync_times[conn.connection_id] = datetime.now(timezone.utc)
        self.store.update_connection(conn)
        return {
            "status": "success",
            "message": f"Updated Google Drive sync schedule to {freq} ({conn.config.auto_sync_interval_minutes} minutes).",
            "sync_frequency": conn.config.sync_frequency,
            "auto_sync_interval_minutes": conn.config.auto_sync_interval_minutes,
            "auto_sync_enabled": conn.config.auto_sync_enabled,
            "webhook_enabled": conn.config.webhook_enabled,
            "connection": conn.to_dict(),
        }

    def disconnect_connection(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        conn.status = GDriveSyncStatus.DISCONNECTED
        conn.current_progress = "Disconnected"
        conn.last_successful_sync_at = None
        self._last_auto_sync_times.pop(conn.connection_id, None)

        if conn.webhook_trigger_id:
            try:
                self.composio.disable_trigger(conn.webhook_trigger_id)
            except Exception as e:
                print(f"[GDriveSyncManager] Error disabling webhook trigger: {e}")

        try:
            self.composio.disconnect_user_account(user_id=user_id, source="gdrive")
        except Exception as e:
            print(f"[GDriveSyncManager] Composio token revocation notice: {e}")

        self.store.release_lock(conn.connection_id)
        self.store.update_connection(conn)
        print(f"[GDriveSyncManager] Disconnected Google Drive for user={user_id}. Memories preserved.")
        return {
            "status": "success",
            "message": "Google Drive disconnected successfully. Vector memories preserved.",
            "connection_id": conn.connection_id,
        }

    async def start_sync_job(
        self,
        connection_id: str,
        trigger_type: GDriveTriggerType = GDriveTriggerType.MANUAL_SYNC,
        is_resync: bool = False,
    ) -> None:
        job_id = f"job_gdrive_{uuid.uuid4().hex[:8]}"
        acquired = self.store.acquire_lock(connection_id=connection_id, job_id=job_id, lease_seconds=900)
        if not acquired:
            print(f"[GDriveSyncManager] Job {job_id} could not acquire lock for connection {connection_id}. Aborting.")
            return

        conn = self.store._connections.get(connection_id)
        if not conn:
            self.store.release_lock(connection_id, job_id)
            return

        conn.status = GDriveSyncStatus.SYNCING
        conn.current_progress = "Discovering Drive files..."
        self.store.update_connection(conn)

        activity = GDriveSyncActivity(
            activity_id=f"act_gdrive_{job_id}",
            job_id=job_id,
            connection_id=conn.connection_id,
            tenant_id=conn.tenant_id,
            trigger_type=trigger_type,
            status="RUNNING",
            started_at=datetime.now(timezone.utc),
            metrics={"total_discovered": 0, "processed": 0, "succeeded": 0, "skipped": 0, "failed": 0},
            items=[],
        )
        self.store.record_activity(activity)

        try:
            limit = conn.config.max_files_per_sync
            is_historical_complete = (conn.backfill_state.historical_sync_status == HistoricalSyncStatus.COMPLETED)

            # Discover eligible files
            if is_historical_complete and not is_resync:
                print(f"[GDriveSyncManager] Backfill COMPLETED for {connection_id}. Running forward incremental sync...")
                eligible_files = self._fetch_forward_incremental_files(conn, max_limit=limit)
            else:
                print(f"[GDriveSyncManager] Executing historical backfill for {connection_id}...")
                eligible_files = self._fetch_eligible_historical_files(conn, max_limit=limit, is_resync=is_resync)

            activity.metrics["total_discovered"] = len(eligible_files)

            if not eligible_files:
                print(f"[GDriveSyncManager] No new files found for {connection_id}.")
                if conn.backfill_state.historical_sync_status == HistoricalSyncStatus.COMPLETED:
                    conn.status = GDriveSyncStatus.UP_TO_DATE
                    conn.current_progress = "Up to date"
                elif getattr(conn.config, "auto_sync_enabled", False) and conn.config.sync_frequency not in ("off", "manual") and (conn.config.auto_sync_interval_minutes or 0) > 0:
                    conn.status = GDriveSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC
                    conn.current_progress = f"Next sync in {conn.config.auto_sync_interval_minutes}m"
                else:
                    conn.status = GDriveSyncStatus.CONNECTED
                    conn.current_progress = "Sync completed"

                conn.last_successful_sync_at = datetime.now(timezone.utc)
                self._last_auto_sync_times[conn.connection_id] = conn.last_successful_sync_at
                self.store.update_connection(conn)

                activity.status = "COMPLETED"
                activity.completed_at = datetime.now(timezone.utc)
                self.store.record_activity(activity)
                self.store.release_lock(connection_id, job_id)
                return

            total_to_process = len(eligible_files)
            processed_so_far = 0
            batch_size = 5
            concurrency_limit = asyncio.Semaphore(5)

            async def _bounded_process(raw_file: dict[str, Any]):
                async with concurrency_limit:
                    return await self._process_single_file(conn, raw_file, activity)

            for i in range(0, total_to_process, batch_size):
                sub_batch = eligible_files[i : i + batch_size]
                batch_num = (i // batch_size) + 1
                total_batches = (total_to_process + batch_size - 1) // batch_size
                print(f"[GDriveSyncManager] Executing Batch {batch_num}/{total_batches} ({len(sub_batch)} files in parallel)...")

                tasks = [_bounded_process(raw_f) for raw_f in sub_batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for res in results:
                    processed_so_far += 1
                    conn.current_progress = f"{processed_so_far} of {total_to_process}"
                    self.store.update_connection(conn)
                    if isinstance(res, Exception):
                        activity.metrics["failed"] += 1
                        print(f"[GDriveSyncManager] Error processing file: {res}")
                    elif res is True:
                        activity.metrics["succeeded"] += 1
                    elif res is False:
                        activity.metrics["skipped"] += 1
                    else:
                        activity.metrics["failed"] += 1

                activity.metrics["processed"] = processed_so_far
                self.store.record_activity(activity)

            # Finalize Connection & Activity State
            conn.last_successful_sync_at = datetime.now(timezone.utc)
            self._last_auto_sync_times[conn.connection_id] = conn.last_successful_sync_at
            conn.backfill_state.total_synced_so_far = self.store.count_synced_files(conn.tenant_id, conn.connection_id)

            if activity.metrics["failed"] > 0:
                conn.status = GDriveSyncStatus.PARTIAL_SUCCESS
                activity.status = "PARTIAL_SUCCESS"
            elif conn.backfill_state.historical_sync_status == HistoricalSyncStatus.COMPLETED:
                conn.status = GDriveSyncStatus.UP_TO_DATE
                conn.current_progress = "Up to date"
                activity.status = "COMPLETED"
            elif getattr(conn.config, "auto_sync_enabled", False) and conn.config.sync_frequency not in ("off", "manual") and (conn.config.auto_sync_interval_minutes or 0) > 0:
                conn.status = GDriveSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC
                conn.current_progress = f"Next sync in {conn.config.auto_sync_interval_minutes}m"
                activity.status = "COMPLETED"
            else:
                conn.status = GDriveSyncStatus.CONNECTED
                conn.current_progress = "Sync completed"
                activity.status = "COMPLETED"

            activity.completed_at = datetime.now(timezone.utc)
            self.store.update_connection(conn)
            self.store.record_activity(activity)
            print(f"[GDriveSyncManager] Completed sync job {job_id} for {connection_id}. Metrics: {activity.metrics}")

        except Exception as err:
            print(f"[GDriveSyncManager] Fatal error in sync job {job_id}: {err}")
            conn.status = GDriveSyncStatus.FAILED
            conn.current_progress = f"Error: {err}"
            activity.status = "FAILED"
            activity.completed_at = datetime.now(timezone.utc)
            self.store.update_connection(conn)
            self.store.record_activity(activity)
        finally:
            self.store.release_lock(connection_id, job_id)

    async def _process_single_file(self, conn: GDriveConnection, raw_file: dict[str, Any], activity: GDriveSyncActivity) -> bool | None:
        file_id = raw_file.get("id") or raw_file.get("fileId") or ""
        filename = raw_file.get("name") or raw_file.get("title") or "Untitled Document"
        mime_type = raw_file.get("mimeType") or "application/octet-stream"
        file_size = int(raw_file.get("size") or raw_file.get("quotaBytesUsed") or 0)

        if not file_id:
            return False

        # Deduplication Guard
        if self.store.is_file_synced(conn.tenant_id, conn.connection_id, file_id):
            return False

        # Skip folders
        if mime_type == "application/vnd.google-apps.folder":
            return False

        # Check File Size Limit
        size_mb = file_size / (1024 * 1024)
        if file_size > 0 and size_mb > conn.config.max_file_size_mb:
            print(f"[GDriveSyncManager] Skipping file {filename} ({size_mb:.1f} MB exceeds {conn.config.max_file_size_mb} MB limit)")
            activity.items.append({
                "file_id": file_id,
                "filename": filename,
                "name": filename,
                "subject": filename,
                "mime_type": mime_type,
                "file_size": file_size,
                "status": "SKIPPED",
                "error_message": f"File size ({size_mb:.1f}MB) exceeds limit ({conn.config.max_file_size_mb}MB)",
                "synced_at": datetime.now(timezone.utc).isoformat(),
            })
            return False

        # Download / Extract text content
        raw_text_content, raw_bytes = self._download_file_content(conn.user_id, file_id, mime_type, filename)

        # Build payload structure for CanonicalEvent normalization
        payload = {
            "metadata": {
                "user_id": conn.user_id,
                "connected_account_id": conn.connection_id,
                "trigger_slug": "GOOGLEDRIVE_FILE_CREATED_TRIGGER",
            },
            "data": {
                "id": file_id,
                "fileId": file_id,
                "name": filename,
                "mimeType": mime_type,
                "size": file_size,
                "modifiedTime": raw_file.get("modifiedTime") or datetime.now(timezone.utc).isoformat(),
                "createdTime": raw_file.get("createdTime") or datetime.now(timezone.utc).isoformat(),
                "webViewLink": raw_file.get("webViewLink", ""),
                "content": raw_text_content,
            }
        }

        event: CanonicalEvent = normalize_gdrive(payload, tenant_id=conn.tenant_id)
        if raw_text_content:
            event.metadata["text_content"] = raw_text_content
            event.metadata["body"] = raw_text_content
            event.metadata["name"] = filename
            event.metadata["subject"] = filename

        try:
            # Process via QueueWorker pipeline (Security -> Parse -> Gatekeeper -> Chunker -> OpenAI -> VectorStore)
            await self.queue_worker._process_event(event)

            # Record Synced File Lineage
            rec = SyncedFileRecord(
                doc_id=f"{event.tenant_id}:{event.source}:{event.external_id}",
                tenant_id=conn.tenant_id,
                connection_id=conn.connection_id,
                file_id=file_id,
                filename=filename,
                mime_type=mime_type,
                size_bytes=file_size,
                categories=conn.config.categories,
                modified_at=event.timestamp,
                sync_status="SUCCESS",
            )
            self.store.record_synced_file(rec)
            conn.backfill_state.total_synced_so_far = self.store.count_synced_files(conn.tenant_id, conn.connection_id)
            self.store.update_connection(conn)

            if event.timestamp:
                event_dt = normalize_to_utc(event.timestamp)
                if not conn.backfill_state.newest_synced_timestamp or event_dt > normalize_to_utc(conn.backfill_state.newest_synced_timestamp):
                    conn.backfill_state.newest_synced_timestamp = ensure_iso_str(event_dt)
                if not conn.backfill_state.oldest_synced_timestamp or event_dt < normalize_to_utc(conn.backfill_state.oldest_synced_timestamp):
                    conn.backfill_state.oldest_synced_timestamp = ensure_iso_str(event_dt)

            activity.items.append({
                "file_id": file_id,
                "filename": filename,
                "name": filename,
                "subject": filename,
                "mime_type": mime_type,
                "file_size": file_size,
                "status": "SUCCESS",
                "synced_at": datetime.now(timezone.utc).isoformat(),
            })
            print(f"[GDriveSyncManager] Successfully synced file {file_id} ('{filename}')")
            return True

        except Exception as err:
            print(f"[GDriveSyncManager] Failed syncing file {file_id}: {err}")
            activity.items.append({
                "file_id": file_id,
                "filename": filename,
                "name": filename,
                "subject": filename,
                "mime_type": mime_type,
                "file_size": file_size,
                "status": "FAILED",
                "error_message": str(err),
                "synced_at": datetime.now(timezone.utc).isoformat(),
            })
            return None


    def _download_file_content(self, user_id: str, file_id: str, mime_type: str, filename: str) -> tuple[str, bytes | None]:
        """
        Downloads and parses file content using Composio tools.
        Supports both:
        1. Google Workspace files (Docs, Sheets, Slides) exported to Markdown/CSV/Text.
        2. Non-Google Workspace files (PDFs, Word Docs, Excel, PowerPoint, Text, Images) downloaded and parsed via LlamaParse.
        """
        if not self.composio._composio:
            # Fallback text representation
            return f"# Document: {filename}\n\nFile ID: {file_id}\nMIME Type: {mime_type}", None

        is_gdoc = mime_type.startswith("application/vnd.google-apps.")
        export_mime = "text/markdown" if "document" in mime_type else "text/csv" if "spreadsheet" in mime_type else "text/plain" if is_gdoc else None

        args: dict[str, Any] = {"fileId": file_id}
        if export_mime:
            args["mime_type"] = export_mime

        try:
            res = self.composio._composio.tools.execute(
                slug="GOOGLEDRIVE_DOWNLOAD_FILE",
                arguments=args,
                user_id=user_id,
                dangerously_skip_version_check=True,
            )
            data = res.get("data", {}) if isinstance(res, dict) else getattr(res, "data", {})
            content = data.get("content") or data.get("text") or data.get("body") or data.get("file_content") or ""
            file_url = data.get("file_url") or data.get("download_url") or data.get("url")
            file_path = data.get("file_path") or data.get("path")

            # 1. Check if a local file path was produced on disk
            if file_path and os.path.exists(file_path):
                try:
                    with open(file_path, "rb") as f:
                        file_bytes = f.read()
                    parsed_text, parser_used, _ = self.queue_worker.parser_service.llama_parser.parse_attachment_bytes(filename, mime_type, file_bytes)
                    if parsed_text and not parsed_text.startswith("*("):
                        return parsed_text, file_bytes
                except Exception as fp_err:
                    print(f"[GDriveSyncManager] Error reading file_path {file_path}: {fp_err}")

            # 2. Check if a downloadable presigned URL was provided
            if file_url and not content:
                try:
                    import urllib.request
                    with urllib.request.urlopen(file_url, timeout=15) as url_resp:
                        file_bytes = url_resp.read()
                    parsed_text, parser_used, _ = self.queue_worker.parser_service.llama_parser.parse_attachment_bytes(filename, mime_type, file_bytes)
                    if parsed_text and not parsed_text.startswith("*("):
                        return parsed_text, file_bytes
                except Exception as dl_err:
                    print(f"[GDriveSyncManager] Error downloading file URL for {filename}: {dl_err}")

            # 3. Check if content is a base64 encoded binary payload (typical for non-workspace binary files)
            if isinstance(content, str) and (content.startswith("data:") or len(content) > 100):
                import base64
                try:
                    raw_b64 = content.split(",")[-1] if "," in content else content
                    decoded_bytes = base64.b64decode(raw_b64)
                    parsed_text, parser_used, _ = self.queue_worker.parser_service.llama_parser.parse_attachment_bytes(filename, mime_type, decoded_bytes)
                    if parsed_text and not parsed_text.startswith("*("):
                        return parsed_text, decoded_bytes
                except Exception:
                    pass

            if content:
                return str(content), None
        except Exception as err:
            print(f"[GDriveSyncManager] Notice: GOOGLEDRIVE_DOWNLOAD_FILE for {file_id} ('{filename}'): {err}")

        # Return rich metadata markdown if binary or download tool was bypassed
        return f"# {filename}\n\n**Google Drive Document**\n- File ID: `{file_id}`\n- Type: `{mime_type}`\n- Name: {filename}", None


    def _fetch_eligible_historical_files(self, conn: GDriveConnection, max_limit: int = 10, is_resync: bool = False) -> list[dict[str, Any]]:
        page_token = conn.backfill_state.next_page_token if not is_resync else None
        files, next_token = self._fetch_gdrive_files_api(conn.user_id, max_results=max_limit, page_token=page_token)

        conn.backfill_state.next_page_token = next_token
        conn.backfill_state.historical_sync_cursor = next_token

        if not next_token:
            conn.backfill_state.historical_sync_status = HistoricalSyncStatus.COMPLETED
            conn.backfill_state.is_backfill_complete = True
            print(f"[GDriveSyncManager] Reached end of Google Drive files for user={conn.user_id}.")
        else:
            conn.backfill_state.historical_sync_status = HistoricalSyncStatus.IN_PROGRESS

        # Filter out already synced files
        eligible = []
        for f in files:
            fid = f.get("id") or f.get("fileId")
            if fid and not self.store.is_file_synced(conn.tenant_id, conn.connection_id, fid):
                eligible.append(f)

        return eligible

    def _fetch_forward_incremental_files(self, conn: GDriveConnection, max_limit: int = 10) -> list[dict[str, Any]]:
        files, _ = self._fetch_gdrive_files_api(conn.user_id, max_results=max_limit)
        eligible = []
        for f in files:
            fid = f.get("id") or f.get("fileId")
            if fid and not self.store.is_file_synced(conn.tenant_id, conn.connection_id, fid):
                eligible.append(f)
        return eligible

    def _fetch_gdrive_files_api(self, user_id: str, max_results: int = 10, page_token: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
        if not self.composio._composio:
            return [], None

        args: dict[str, Any] = {
            "pageSize": min(max(max_results, 1), 50),
            "q": "trashed = false and mimeType != 'application/vnd.google-apps.folder'",
            "fields": "nextPageToken, files(id, name, mimeType, size, webViewLink, modifiedTime, createdTime, owners)",
            "orderBy": "modifiedTime desc",
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if page_token:
            args["pageToken"] = page_token

        try:
            res = self.composio._composio.tools.execute(
                slug="GOOGLEDRIVE_LIST_FILES",
                arguments=args,
                user_id=user_id,
                dangerously_skip_version_check=True,
            )
            data = res.get("data", {}) if isinstance(res, dict) else getattr(res, "data", {})
            if isinstance(data, dict):
                file_list = data.get("files") or data.get("data", {}).get("files") or []
                next_tok = data.get("nextPageToken") or (data.get("data", {}).get("nextPageToken") if isinstance(data.get("data"), dict) else None)
                print(f"[GDriveSyncManager] Successfully fetched {len(file_list)} live Drive files for user_id={user_id} (nextPageToken={next_tok}).")
                return file_list, next_tok
            return [], None
        except Exception as err:
            print(f"[GDriveSyncManager] Error executing GOOGLEDRIVE_LIST_FILES: {err}")
            return [], None

    async def process_webhook_event(self, event: CanonicalEvent, raw_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Processes real-time Google Drive file webhook events."""
        conn = self.store.get_or_create_connection(tenant_id=event.tenant_id, user_id=event.user_id)

        if not getattr(conn.config, "webhook_enabled", False):
            print(f"[GDriveSyncManager] Webhook: Webhook triggers are disabled for user={conn.user_id}. Skipping event.")
            return {"status": "ignored", "reason": "Webhook triggers are disabled"}

        file_id = event.external_id
        if not file_id or file_id == "unknown_file_id":
            file_id = event.metadata.get("file_id") or (raw_payload or {}).get("data", {}).get("id", "")

        if not file_id:
            return {"status": "ignored", "reason": "Missing file ID"}

        # Deduplication Guard
        if self.store.is_file_synced(conn.tenant_id, conn.connection_id, file_id):
            print(f"[GDriveSyncManager] Webhook: file_id={file_id} already synced. Skipping duplicate.")
            return {
                "status": "ignored",
                "reason": "Duplicate file (already indexed)",
                "file_id": file_id,
                "connection_id": conn.connection_id,
            }

        raw_file = None
        if raw_payload:
            raw_file = raw_payload.get("data") or raw_payload.get("payload")
        if not isinstance(raw_file, dict):
            raw_file = {
                "id": file_id,
                "name": event.metadata.get("name", "Untitled Document"),
                "mimeType": event.metadata.get("mime_type", "application/octet-stream"),
                "size": event.metadata.get("file_size", 0),
                "modifiedTime": event.timestamp.isoformat() if event.timestamp else datetime.now(timezone.utc).isoformat(),
                "webViewLink": event.metadata.get("web_view_link", ""),
            }

        if "id" not in raw_file:
            raw_file["id"] = file_id

        activity_id = f"act_gdrive_webhook_{uuid.uuid4().hex[:10]}"
        job_id = f"job_gdrive_webhook_{uuid.uuid4().hex[:8]}"
        activity = GDriveSyncActivity(
            activity_id=activity_id,
            job_id=job_id,
            connection_id=conn.connection_id,
            tenant_id=conn.tenant_id,
            trigger_type=GDriveTriggerType.WEBHOOK,
            status="RUNNING",
            started_at=datetime.now(timezone.utc),
            metrics={"total_discovered": 1, "processed": 0, "succeeded": 0, "skipped": 0, "failed": 0},
            items=[],
        )
        self.store.record_activity(activity)

        try:
            result = await self._process_single_file(conn, raw_file, activity)
            if result is True:
                activity.metrics["processed"] = 1
                activity.metrics["succeeded"] = 1
                activity.status = "COMPLETED"
                conn.last_successful_sync_at = datetime.now(timezone.utc)
                conn.backfill_state.total_synced_so_far = self.store.count_synced_files(conn.tenant_id, conn.connection_id)
                self.store.update_connection(conn)
                print(f"[GDriveSyncManager] Webhook indexed file {file_id} successfully.")
            elif result is False:
                activity.metrics["processed"] = 1
                activity.metrics["skipped"] = 1
                activity.status = "COMPLETED"
            else:
                activity.metrics["processed"] = 1
                activity.metrics["failed"] = 1
                activity.status = "FAILED"
        except Exception as err:
            print(f"[GDriveSyncManager] Webhook error processing file {file_id}: {err}")
            activity.metrics["processed"] = 1
            activity.metrics["failed"] = 1
            activity.status = "FAILED"

        activity.completed_at = datetime.now(timezone.utc)
        self.store.record_activity(activity)

        return {
            "status": "indexed" if activity.status == "COMPLETED" and activity.metrics["succeeded"] > 0 else "failed",
            "file_id": file_id,
            "activity_id": activity.activity_id,
            "connection_id": conn.connection_id,
            "metrics": activity.metrics,
        }

    async def _auto_sync_loop(self) -> None:
        """
        Background scheduler executing auto-sync:
        - Evaluates each active connection against its configured auto_sync_interval_minutes (2m, 30m, 1h, 6h, 24h at 2am).
        - Strictly verifies active OAuth connectivity with Composio before attempting any sync.
        - Anchors next auto-sync to the last successful sync completion time (never fires immediately after backfill).
        - If connection is disconnected or disabled, skips completely.
        """
        while self._is_scheduler_running:
            try:
                # Periodic tick every 20 seconds for responsive auto-sync triggers
                await asyncio.sleep(20)
                now = datetime.now(timezone.utc)
                active_connections = self.store.list_all_active_connections()

                for conn in active_connections:
                    # Only run auto-sync for connected tools in ready states
                    if conn.status not in (
                        GDriveSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC,
                        GDriveSyncStatus.UP_TO_DATE,
                        GDriveSyncStatus.CONNECTED,
                        GDriveSyncStatus.PARTIAL_SUCCESS,
                    ) or self.store.is_locked(conn.connection_id):
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
                        if elapsed_seconds >= 86400 or (now.hour == 2 and now.date() > last_run.date()):
                            should_run = True
                    else:
                        if elapsed_seconds >= (interval_mins * 60):
                            should_run = True

                    if not should_run or self.store.is_locked(conn.connection_id):
                        continue

                    # Strictly verify active OAuth connectivity with Composio ONLY when sync is ready to run
                    try:
                        if not self.composio.is_account_connected(user_id=conn.user_id, source="gdrive"):
                            continue
                    except Exception as oauth_err:
                        print(f"[GDriveSyncManager] OAuth connectivity check notice: {oauth_err}")
                        continue

                    self._last_auto_sync_times[conn.connection_id] = now
                    print(f"[GDriveSyncManager] Auto-sync triggered for {conn.connection_id} after {elapsed_seconds:.1f}s.")
                    asyncio.create_task(self.start_sync_job(conn.connection_id, trigger_type=GDriveTriggerType.AUTO_SYNC))
            except asyncio.CancelledError:
                break
            except Exception as err:
                print(f"[GDriveSyncManager] Error in auto-sync cron loop: {err}")

    def get_data_summary(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        """Calculates current count of synced raw files, activity runs, and vector memory for pre-deletion preview."""
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        summary = self.store.get_data_summary(tenant_id=conn.tenant_id, connection_id=conn.connection_id)

        try:
            vector_count = self.queue_worker.ingestion_pipeline.vector_store.count_vectors(
                tenant_id=tenant_id, source="gdrive", user_id=user_id
            )
        except Exception:
            from module_3_batch_ingestion_vector.vector_store import VectorStore
            vs = VectorStore()
            vector_count = vs.count_vectors(tenant_id=tenant_id, source="gdrive", user_id=user_id)

        # Fallback: if vector store count is 0 but synced files exist, reflect count from synced files
        if vector_count == 0 and summary.get("synced_files_count", 0) > 0:
            vector_count = summary.get("synced_files_count", 0)

        summary["vector_records_count"] = vector_count
        summary["source"] = "gdrive"
        summary["user_id"] = user_id
        return summary

    async def purge_all_connector_data(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        store_res = self.store.purge_all_synced_data(tenant_id=conn.tenant_id, connection_id=conn.connection_id)

        vectors_deleted = 0
        try:
            vectors_deleted = self.queue_worker.ingestion_pipeline.vector_store.delete_by_tenant_source_user(
                tenant_id=tenant_id, source="gdrive", user_id=user_id
            )
        except Exception as e:
            from module_3_batch_ingestion_vector.vector_store import VectorStore
            vs = VectorStore()
            vectors_deleted = vs.delete_by_tenant_source_user(tenant_id=tenant_id, source="gdrive", user_id=user_id)

        docs_purged = 0
        try:
            docs_purged = self.queue_worker.store.purge_by_tenant_source_user(
                tenant_id=tenant_id, source="gdrive", user_id=user_id
            )
        except Exception as e:
            print(f"[GDriveSyncManager] Canonical doc deletion notice: {e}")

        return {
            "status": "success",
            "message": f"Purged all Google Drive data for user {user_id}.",
            "purged_metrics": {
                "synced_files_deleted": store_res.get("synced_files_deleted", 0),
                "activities_deleted": store_res.get("activities_deleted", 0),
                "vectors_deleted": vectors_deleted,
                "canonical_docs_deleted": docs_purged,
            },
        }
