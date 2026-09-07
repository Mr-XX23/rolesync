import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from module_1_document_processing.composio_connector.composio_client import ComposioClient
from module_1_document_processing.composio_connector.calendar_models import (
    CalendarConnection,
    CalendarSyncConfig,
    CalendarBackfillState,
    CalendarSyncStatus,
    CalendarTriggerType,
    HistoricalSyncStatus,
    SyncPhase,
    SyncedEventRecord,
    CalendarSyncActivity,
)
from module_1_document_processing.composio_connector.calendar_store import CalendarStore
from module_1_document_processing.composio_connector.normalizers.calendar_normalizer import normalize_calendar
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.composio_connector.date_utils import normalize_to_utc, ensure_iso_str
from module_1_document_processing.pipeline.queue_worker import QueueWorker

class CalendarSyncManager:
    """Production Sync Manager orchestrating Google Calendar OAuth, 2-phase ingestion (Future 1 Year -> Past 180 Days), auto-sync, and real-time webhooks."""

    def __init__(
        self,
        composio_client: ComposioClient | None = None,
        store: CalendarStore | None = None,
        queue_worker: QueueWorker | None = None,
    ) -> None:
        self.composio = composio_client or ComposioClient()
        self.store = store or CalendarStore()
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
        print(f"[CalendarSyncManager] Auto-sync scheduler running (interval: {self.auto_sync_interval_minutes}m).")

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
        print("[CalendarSyncManager] Background auto-sync scheduler stopped.")

    def get_connection_status(self, user_id: str, tenant_id: str = "tenant_default") -> CalendarConnection:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        is_authenticated = self.composio.is_account_connected(user_id=user_id, source="google_calendar")

        synced_count = self.store.count_synced_events(conn.tenant_id, conn.connection_id)
        changed = False
        if conn.backfill_state.total_synced_so_far != synced_count:
            conn.backfill_state.total_synced_so_far = synced_count
            changed = True

        old_status = conn.status
        old_progress = conn.current_progress

        if is_authenticated:
            if conn.status in (CalendarSyncStatus.AVAILABLE, CalendarSyncStatus.DISCONNECTED, CalendarSyncStatus.CONFIGURATION_REQUIRED):
                if synced_count > 0 or conn.last_successful_sync_at is not None or conn.backfill_state.is_backfill_complete:
                    if conn.backfill_state.is_backfill_complete:
                        conn.status = CalendarSyncStatus.UP_TO_DATE
                        if not conn.current_progress or conn.current_progress.lower().startswith("error"):
                            conn.current_progress = "Up to date"
                    elif getattr(conn.config, "auto_sync_enabled", False) and conn.config.sync_frequency not in ("off", "manual") and (conn.config.auto_sync_interval_minutes or 0) > 0:
                        conn.status = CalendarSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC
                        if not conn.current_progress:
                            conn.current_progress = f"Next sync in {conn.config.auto_sync_interval_minutes}m"
                    else:
                        conn.status = CalendarSyncStatus.CONNECTED
                        if not conn.current_progress:
                            conn.current_progress = "Sync completed"
                else:
                    conn.status = CalendarSyncStatus.CONFIGURATION_REQUIRED
        else:
            if conn.status in (
                CalendarSyncStatus.CONFIGURATION_REQUIRED,
                CalendarSyncStatus.CONNECTED,
                CalendarSyncStatus.SYNCING,
                CalendarSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC,
                CalendarSyncStatus.UP_TO_DATE,
                CalendarSyncStatus.PARTIAL_SUCCESS,
            ):
                conn.status = CalendarSyncStatus.AVAILABLE

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
        redirect_url = self.composio.initiate_user_connection(user_id=user_id, source="google_calendar", callback_url=callback_url)
        trigger_id = None
        if getattr(conn.config, "webhook_enabled", False):
            trigger_id = self.composio.enable_trigger(trigger_slug=ComposioClient.CALENDAR_EVENT_UPDATED, user_id=user_id)

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
        config: CalendarSyncConfig | None = None,
    ) -> dict[str, Any]:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        if config:
            # Ensure PRIMARY is included by default if empty
            if not config.categories:
                config.categories = ["PRIMARY"]
            conn.config = config

        now = datetime.now(timezone.utc)
        conn.last_successful_sync_at = now
        self._last_auto_sync_times[conn.connection_id] = now

        conn.status = CalendarSyncStatus.SYNCING
        conn.current_progress = "Starting Google Calendar synchronization..."
        self.store.update_connection(conn)

        # Launch non-blocking sync job in background safely
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.start_sync_job(conn.connection_id, trigger_type=CalendarTriggerType.INITIAL_SYNC))
        except RuntimeError:
            import threading
            threading.Thread(
                target=lambda: asyncio.run(self.start_sync_job(conn.connection_id, trigger_type=CalendarTriggerType.INITIAL_SYNC)),
                daemon=True,
            ).start()

        return {
            "status": "success",
            "message": "Google Calendar synchronization initiated.",
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
                        trigger_slug=ComposioClient.CALENDAR_EVENT_UPDATED, user_id=user_id
                    )
            else:
                if conn.webhook_trigger_id:
                    self.composio.disable_trigger(conn.webhook_trigger_id)
                    conn.webhook_trigger_id = None
        except Exception as trig_err:
            print(f"[CalendarSyncManager] Webhook trigger toggle notice: {trig_err}")

        if not conn.config.auto_sync_enabled or freq in ("off", "manual"):
            if conn.status == CalendarSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC:
                conn.status = CalendarSyncStatus.CONNECTED
                conn.current_progress = "Auto-sync disabled (Manual only)"
        elif conn.status == CalendarSyncStatus.CONNECTED:
            conn.status = CalendarSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC
            conn.current_progress = f"Next sync in {conn.config.auto_sync_interval_minutes}m"

        self._last_auto_sync_times[conn.connection_id] = datetime.now(timezone.utc)
        self.store.update_connection(conn)
        return {
            "status": "success",
            "message": f"Updated Google Calendar sync schedule to {freq} ({conn.config.auto_sync_interval_minutes} minutes).",
            "sync_frequency": conn.config.sync_frequency,
            "auto_sync_interval_minutes": conn.config.auto_sync_interval_minutes,
            "auto_sync_enabled": conn.config.auto_sync_enabled,
            "webhook_enabled": conn.config.webhook_enabled,
            "connection": conn.to_dict(),
        }

    def disconnect_connection(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        conn.status = CalendarSyncStatus.DISCONNECTED
        conn.current_progress = "Disconnected"
        conn.last_successful_sync_at = None
        self._last_auto_sync_times.pop(conn.connection_id, None)

        if conn.webhook_trigger_id:
            try:
                self.composio.disable_trigger(conn.webhook_trigger_id)
            except Exception as e:
                print(f"[CalendarSyncManager] Error disabling webhook trigger: {e}")

        try:
            self.composio.disconnect_user_account(user_id=user_id, source="google_calendar")
        except Exception as e:
            print(f"[CalendarSyncManager] Composio token revocation notice: {e}")

        self.store.release_lock(conn.connection_id)
        self.store.update_connection(conn)
        print(f"[CalendarSyncManager] Disconnected Google Calendar for user={user_id}. Vector memories preserved.")
        return {
            "status": "success",
            "message": "Google Calendar disconnected successfully. Vector memories preserved.",
            "connection_id": conn.connection_id,
        }

    async def start_sync_job(
        self,
        connection_id: str,
        trigger_type: CalendarTriggerType = CalendarTriggerType.MANUAL_SYNC,
        is_resync: bool = False,
    ) -> None:
        """
        Executes two-phase synchronization:
        Phase 1: Ingest future 1-year events (now to now + 365 days) on Primary Calendar by default.
        Phase 2: Ingest historical past 180-day events (now - 180 days to now).
        """
        job_id = f"job_cal_{uuid.uuid4().hex[:8]}"
        acquired = self.store.acquire_lock(connection_id=connection_id, job_id=job_id, lease_seconds=900)
        if not acquired:
            print(f"[CalendarSyncManager] Job {job_id} could not acquire lock for connection {connection_id}. Aborting.")
            return

        conn = self.store._connections.get(connection_id)
        if not conn:
            self.store.release_lock(connection_id, job_id)
            return

        conn.status = CalendarSyncStatus.SYNCING
        conn.current_progress = "Discovering calendar events..."
        self.store.update_connection(conn)

        activity = CalendarSyncActivity(
            activity_id=f"act_cal_{job_id}",
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
            now_dt = datetime.now(timezone.utc)
            limit = conn.config.max_events_per_sync

            # Reset backfill state if resync
            if is_resync:
                conn.backfill_state = CalendarBackfillState()
                conn.backfill_state.current_phase = SyncPhase.FUTURE_1_YEAR
                self.store.update_connection(conn)

            # =========================================================================
            # PHASE 1: INGEST FUTURE 1-YEAR EVENTS (now -> now + 365 days)
            # =========================================================================
            if not conn.backfill_state.is_future_complete:
                conn.current_progress = "Syncing upcoming events (1 Year)..."
                self.store.update_connection(conn)

                time_min_str = ensure_iso_str(now_dt)
                time_max_str = ensure_iso_str(now_dt + timedelta(days=conn.config.future_window_days))

                future_events, next_fut_token = self._fetch_calendar_events_api(
                    user_id=conn.user_id,
                    time_min=time_min_str,
                    time_max=time_max_str,
                    max_results=limit,
                    page_token=conn.backfill_state.future_sync_cursor,
                    categories=conn.config.categories,
                )

                conn.backfill_state.future_sync_cursor = next_fut_token
                if not next_fut_token:
                    conn.backfill_state.is_future_complete = True
                    print(f"[CalendarSyncManager] Reached end of future 1-year calendar events for {connection_id}.")

                # Filter unsynced
                eligible_future = [
                    e for e in future_events
                    if (e.get("id") or e.get("eventId"))
                    and not self.store.is_event_synced(conn.tenant_id, conn.connection_id, e.get("id") or e.get("eventId"))
                ]

                activity.metrics["total_discovered"] += len(eligible_future)
                if eligible_future:
                    print(f"[CalendarSyncManager] Processing {len(eligible_future)} future calendar events...")
                    await self._process_events_batch(conn, eligible_future, activity, "upcoming")

            # =========================================================================
            # PHASE 2: INGEST HISTORICAL PAST 180-DAY EVENTS (now - 180 days -> now)
            # =========================================================================
            if conn.backfill_state.is_future_complete and not conn.backfill_state.is_past_complete:
                conn.current_progress = "Syncing past events (180 Days)..."
                self.store.update_connection(conn)

                past_min_str = ensure_iso_str(now_dt - timedelta(days=conn.config.sync_window_days))
                past_max_str = ensure_iso_str(now_dt)

                past_events, next_past_token = self._fetch_calendar_events_api(
                    user_id=conn.user_id,
                    time_min=past_min_str,
                    time_max=past_max_str,
                    max_results=limit,
                    page_token=conn.backfill_state.past_sync_cursor,
                    categories=conn.config.categories,
                )

                conn.backfill_state.past_sync_cursor = next_past_token
                if not next_past_token:
                    conn.backfill_state.is_past_complete = True
                    conn.backfill_state.is_backfill_complete = True
                    conn.backfill_state.historical_sync_status = HistoricalSyncStatus.COMPLETED
                    print(f"[CalendarSyncManager] Reached end of past 180-day calendar events for {connection_id}.")

                eligible_past = [
                    e for e in past_events
                    if (e.get("id") or e.get("eventId"))
                    and not self.store.is_event_synced(conn.tenant_id, conn.connection_id, e.get("id") or e.get("eventId"))
                ]

                activity.metrics["total_discovered"] += len(eligible_past)
                if eligible_past:
                    print(f"[CalendarSyncManager] Processing {len(eligible_past)} historical calendar events...")
                    await self._process_events_batch(conn, eligible_past, activity, "historical")

            # Update count and final status
            conn.last_successful_sync_at = datetime.now(timezone.utc)
            self._last_auto_sync_times[conn.connection_id] = conn.last_successful_sync_at
            conn.backfill_state.total_synced_so_far = self.store.count_synced_events(conn.tenant_id, conn.connection_id)

            if activity.metrics["failed"] > 0:
                conn.status = CalendarSyncStatus.PARTIAL_SUCCESS
                activity.status = "PARTIAL_SUCCESS"
            elif conn.backfill_state.is_backfill_complete:
                conn.status = CalendarSyncStatus.UP_TO_DATE
                conn.current_progress = "Up to date"
                activity.status = "COMPLETED"
            elif getattr(conn.config, "auto_sync_enabled", False) and conn.config.sync_frequency not in ("off", "manual") and (conn.config.auto_sync_interval_minutes or 0) > 0:
                conn.status = CalendarSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC
                conn.current_progress = f"Next sync in {conn.config.auto_sync_interval_minutes}m"
                activity.status = "COMPLETED"
            else:
                conn.status = CalendarSyncStatus.CONNECTED
                conn.current_progress = "Sync completed"
                activity.status = "COMPLETED"

            activity.completed_at = datetime.now(timezone.utc)
            self.store.update_connection(conn)
            self.store.record_activity(activity)
            print(f"[CalendarSyncManager] Completed sync job {job_id} for {connection_id}. Metrics: {activity.metrics}")

        except Exception as err:
            print(f"[CalendarSyncManager] Fatal error in sync job {job_id}: {err}")
            conn.status = CalendarSyncStatus.FAILED
            conn.current_progress = f"Error: {err}"
            activity.status = "FAILED"
            activity.completed_at = datetime.now(timezone.utc)
            self.store.update_connection(conn)
            self.store.record_activity(activity)
        finally:
            self.store.release_lock(connection_id, job_id)

    async def _process_events_batch(
        self,
        conn: CalendarConnection,
        events: list[dict[str, Any]],
        activity: CalendarSyncActivity,
        phase_label: str,
    ) -> None:
        total_to_process = len(events)
        processed_so_far = activity.metrics["processed"]
        batch_size = 5
        concurrency_limit = asyncio.Semaphore(5)

        async def _bounded_process(raw_event: dict[str, Any]):
            async with concurrency_limit:
                return await self._process_single_event(conn, raw_event, activity)

        for i in range(0, total_to_process, batch_size):
            sub_batch = events[i : i + batch_size]
            tasks = [_bounded_process(e) for e in sub_batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in results:
                processed_so_far += 1
                conn.current_progress = f"Syncing {phase_label} events ({processed_so_far} of {activity.metrics['total_discovered']})"
                self.store.update_connection(conn)

                if isinstance(res, Exception):
                    activity.metrics["failed"] += 1
                    print(f"[CalendarSyncManager] Error processing event: {res}")
                elif res is True:
                    activity.metrics["succeeded"] += 1
                elif res is False:
                    activity.metrics["skipped"] += 1
                else:
                    activity.metrics["failed"] += 1

            activity.metrics["processed"] = processed_so_far
            self.store.record_activity(activity)

    async def _process_single_event(
        self,
        conn: CalendarConnection,
        raw_event: dict[str, Any],
        activity: CalendarSyncActivity,
    ) -> bool | None:
        event_id = raw_event.get("id") or raw_event.get("eventId") or ""
        summary = raw_event.get("summary") or raw_event.get("title") or "(Untitled Meeting)"
        status_raw = (raw_event.get("status") or "").lower()

        if not event_id:
            return False

        # Handle Cancelled / Deleted Events
        if status_raw in ("cancelled", "deleted"):

            print(f"[CalendarSyncManager] Event {event_id} ('{summary}') is cancelled/deleted. Emitting DELETE event.")
            del_event = CanonicalEvent(
                event_id=f"cal_{conn.tenant_id}_{event_id}",
                event_type=EventType.DELETE,
                source="google_calendar",
                tenant_id=conn.tenant_id,
                user_id=conn.user_id,
                external_id=event_id,
                raw_ref={"event_id": event_id},
                acl=[conn.user_id],
                timestamp=datetime.now(timezone.utc),
                metadata={"status": "cancelled", "summary": summary},
            )
            await self.queue_worker._process_event(del_event)
            self.store.delete_synced_event(conn.tenant_id, conn.connection_id, event_id)
            activity.items.append({
                "event_id": event_id,
                "summary": summary,
                "status": "DELETED",
                "synced_at": datetime.now(timezone.utc).isoformat(),
            })
            return True

        # Deduplication Guard
        if self.store.is_event_synced(conn.tenant_id, conn.connection_id, event_id):
            return False


        # Extract timing (supporting both date and dateTime)
        start_obj = raw_event.get("start") or {}
        end_obj = raw_event.get("end") or {}
        start_time_raw = start_obj.get("dateTime") or start_obj.get("date") or datetime.now(timezone.utc).isoformat()
        end_time_raw = end_obj.get("dateTime") or end_obj.get("date") or start_time_raw

        # Format attendees & organizer
        attendees_raw = raw_event.get("attendees") or []
        attendees = [a.get("email") for a in attendees_raw if isinstance(a, dict) and a.get("email")]
        organizer = raw_event.get("organizer", {}).get("email") if isinstance(raw_event.get("organizer"), dict) else (raw_event.get("creator", {}).get("email") if isinstance(raw_event.get("creator"), dict) else "")

        location = raw_event.get("location") or ""
        hangout_link = raw_event.get("hangoutLink") or raw_event.get("htmlLink") or raw_event.get("meetLink") or ""
        description = raw_event.get("description") or "*(No meeting description or agenda provided)*"
        cal_id = raw_event.get("calendarId", "primary")

        # Format Meeting Transcript Markdown
        text_content = (
            f"# Meeting: {summary}\n\n"
            f"**Calendar:** `{cal_id}`  \n"
            f"**Start Time:** {start_time_raw}  \n"
            f"**End Time:** {end_time_raw}  \n"
            f"**Organizer:** {organizer or 'Unknown'}  \n"
            f"**Attendees:** {', '.join(attendees) if attendees else 'None listed'}  \n"
            f"**Location / Meet Link:** {location or hangout_link or 'None'}  \n\n"
            f"## Meeting Details & Agenda\n"
            f"{description}\n"
        )

        payload = {
            "metadata": {
                "user_id": conn.user_id,
                "connected_account_id": conn.connection_id,
                "trigger_slug": ComposioClient.CALENDAR_EVENT_UPDATED,
                "log_id": f"log_cal_{event_id}",
            },
            "data": {
                **raw_event,
                "id": event_id,
                "summary": summary,
                "description": description,
                "location": location,
                "hangoutLink": hangout_link,
                "start": start_obj if isinstance(start_obj, dict) else {"dateTime": start_time_raw},
                "end": end_obj if isinstance(end_obj, dict) else {"dateTime": end_time_raw},
            },
        }

        canonical_event: CanonicalEvent = normalize_calendar(payload, tenant_id=conn.tenant_id)
        canonical_event.metadata["text_content"] = text_content
        canonical_event.metadata["body"] = text_content
        canonical_event.metadata["summary"] = summary
        canonical_event.metadata["subject"] = summary
        canonical_event.metadata["mime_type"] = "text/markdown"

        try:
            # Process via QueueWorker pipeline (Security -> Parse -> Gatekeeper -> Chunker -> OpenAI -> VectorStore)
            await self.queue_worker._process_event(canonical_event)

            # Record Synced Event Lineage
            rec = SyncedEventRecord(
                doc_id=f"{canonical_event.tenant_id}:{canonical_event.source}:{canonical_event.external_id}",
                tenant_id=conn.tenant_id,
                connection_id=conn.connection_id,
                event_id=event_id,
                summary=summary,
                organizer=organizer,
                attendees=attendees,
                start_time=str(start_time_raw),
                end_time=str(end_time_raw),
                location=location,
                hangout_link=hangout_link,
                categories=conn.config.categories,
                sync_status="SUCCESS",
            )
            self.store.record_synced_event(rec)
            conn.backfill_state.total_synced_so_far = self.store.count_synced_events(conn.tenant_id, conn.connection_id)
            self.store.update_connection(conn)

            event_dt = normalize_to_utc(start_time_raw)
            if not conn.backfill_state.newest_synced_timestamp or event_dt > normalize_to_utc(conn.backfill_state.newest_synced_timestamp):
                conn.backfill_state.newest_synced_timestamp = ensure_iso_str(event_dt)
            if not conn.backfill_state.oldest_synced_timestamp or event_dt < normalize_to_utc(conn.backfill_state.oldest_synced_timestamp):
                conn.backfill_state.oldest_synced_timestamp = ensure_iso_str(event_dt)

            activity.items.append({
                "event_id": event_id,
                "summary": summary,
                "subject": summary,
                "status": "SUCCESS",
                "start_time": str(start_time_raw),
                "organizer": organizer,
                "synced_at": datetime.now(timezone.utc).isoformat(),
            })
            print(f"[CalendarSyncManager] Successfully synced event {event_id} ('{summary}')")
            return True

        except Exception as err:
            print(f"[CalendarSyncManager] Failed syncing event {event_id}: {err}")
            activity.items.append({
                "event_id": event_id,
                "summary": summary,
                "subject": summary,
                "status": "FAILED",
                "error_message": str(err),
                "synced_at": datetime.now(timezone.utc).isoformat(),
            })
            return False

    def _fetch_calendar_events_api(
        self,
        user_id: str,
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = 10,
        page_token: str | None = None,
        categories: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Queries Google Calendar events via Composio SDK with date filtering and pagination."""
        if not self.composio._composio:
            return [], None

        args: dict[str, Any] = {
            "calendarId": "primary",
            "maxResults": min(max(max_results, 1), 50),
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_min:
            args["timeMin"] = time_min
        if time_max:
            args["timeMax"] = time_max
        if page_token:
            args["pageToken"] = page_token

        # Try Composio Google Calendar tools
        tool_slugs = ["GOOGLECALENDAR_LIST_EVENTS", "GOOGLECALENDAR_FIND_EVENT", "GOOGLE_CALENDAR_LIST_EVENTS"]
        for slug in tool_slugs:
            try:
                res = self.composio._composio.tools.execute(
                    slug=slug,
                    arguments=args,
                    user_id=user_id,
                    dangerously_skip_version_check=True,
                )
                data = res.get("data", {}) if isinstance(res, dict) else getattr(res, "data", {})
                if isinstance(data, dict):
                    # Handle varying Composio v3 Google Calendar response structures
                    event_data_wrapper = data.get("event_data")
                    nested_items = None
                    if isinstance(event_data_wrapper, dict):
                        nested_items = event_data_wrapper.get("event_data") or event_data_wrapper.get("items") or event_data_wrapper.get("events")
                    elif isinstance(event_data_wrapper, list):
                        nested_items = event_data_wrapper

                    items = (
                        nested_items
                        or data.get("items")
                        or data.get("events")
                        or data.get("data", {}).get("items")
                        or []
                    )
                    next_tok = (
                        (isinstance(event_data_wrapper, dict) and event_data_wrapper.get("nextPageToken"))
                        or data.get("nextPageToken")
                        or (data.get("data", {}).get("nextPageToken") if isinstance(data.get("data"), dict) else None)
                    )
                    print(f"[CalendarSyncManager] Fetched {len(items)} live Calendar events using {slug} for user={user_id}.")
                    return items, next_tok
            except Exception as err:
                print(f"[CalendarSyncManager] Attempt with tool {slug} yielded: {err}")

        return [], None

    async def process_webhook_event(self, event: CanonicalEvent, raw_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Processes incoming real-time Google Calendar webhook notifications."""
        conn = self.store.get_or_create_connection(tenant_id=event.tenant_id, user_id=event.user_id)

        if not getattr(conn.config, "webhook_enabled", False):
            print(f"[CalendarSyncManager] Webhook: triggers are disabled for user={conn.user_id}. Skipping event.")
            return {"status": "ignored", "reason": "Webhook triggers are disabled"}

        event_id = event.external_id
        if not event_id or event_id == "unknown_event_id":
            event_id = event.metadata.get("event_id") or (raw_payload or {}).get("data", {}).get("id", "")

        if not event_id:
            return {"status": "ignored", "reason": "Missing event ID"}

        # Handle cancellation via webhook
        status_val = (event.metadata.get("status") or (raw_payload or {}).get("data", {}).get("status", "")).lower()
        if status_val in ("cancelled", "deleted"):
            del_event = CanonicalEvent(
                event_id=f"cal_{conn.tenant_id}_{event_id}",
                event_type=EventType.DELETE,
                source="google_calendar",
                tenant_id=conn.tenant_id,
                user_id=conn.user_id,
                external_id=event_id,
                raw_ref={"event_id": event_id},
                acl=[conn.user_id],
                timestamp=datetime.now(timezone.utc),
                metadata={"status": "cancelled"},
            )
            await self.queue_worker._process_event(del_event)
            self.store.delete_synced_event(conn.tenant_id, conn.connection_id, event_id)
            return {"status": "deleted", "event_id": event_id}

        # Deduplication Guard
        if self.store.is_event_synced(conn.tenant_id, conn.connection_id, event_id):
            print(f"[CalendarSyncManager] Webhook: event_id={event_id} already synced. Skipping duplicate.")
            return {"status": "ignored", "reason": "Duplicate event (already indexed)", "event_id": event_id}

        activity = CalendarSyncActivity(
            activity_id=f"act_cal_webhook_{uuid.uuid4().hex[:8]}",
            job_id=f"job_cal_webhook_{event_id[:6]}",
            connection_id=conn.connection_id,
            tenant_id=conn.tenant_id,
            trigger_type=CalendarTriggerType.WEBHOOK,
            status="RUNNING",
            metrics={"total_discovered": 1, "processed": 0, "succeeded": 0, "skipped": 0, "failed": 0},
            items=[],
        )
        self.store.record_activity(activity)

        raw_event_data = (raw_payload or {}).get("data") or {
            "id": event_id,
            "summary": event.metadata.get("summary") or event.metadata.get("subject") or "(Webhook Event)",
            "start": {"dateTime": event.metadata.get("start_time") or event.timestamp.isoformat()},
            "end": {"dateTime": event.metadata.get("end_time") or event.timestamp.isoformat()},
            "organizer": {"email": event.metadata.get("organizer")},
            "description": event.metadata.get("description"),
            "location": event.metadata.get("location"),
            "hangoutLink": event.metadata.get("hangout_link"),
        }

        success = await self._process_single_event(conn, raw_event_data, activity)
        activity.status = "COMPLETED" if success else "FAILED"
        activity.completed_at = datetime.now(timezone.utc)
        if success:
            activity.metrics["succeeded"] = 1
        else:
            activity.metrics["failed"] = 1
        activity.metrics["processed"] = 1

        self.store.record_activity(activity)
        return {"status": "processed" if success else "failed", "event_id": event_id}

    async def _auto_sync_loop(self) -> None:
        """Background loop executing scheduled auto-sync for connected Google Calendar accounts."""
        while self._is_scheduler_running:
            try:
                await asyncio.sleep(60)
                now = datetime.now(timezone.utc)
                connections = list(self.store._connections.values())
                for conn in connections:
                    if conn.status not in (
                        CalendarSyncStatus.CONNECTED,
                        CalendarSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC,
                        CalendarSyncStatus.UP_TO_DATE,
                        CalendarSyncStatus.PARTIAL_SUCCESS,
                    ):
                        continue

                    if not getattr(conn.config, "auto_sync_enabled", False):
                        continue

                    interval_m = conn.config.auto_sync_interval_minutes or 30
                    if interval_m <= 0:
                        continue

                    last_sync = self._last_auto_sync_times.get(conn.connection_id) or conn.last_successful_sync_at or conn.created_at
                    if (now - last_sync).total_seconds() >= (interval_m * 60):
                        if not self.store.is_locked(conn.connection_id):
                            print(f"[CalendarSyncManager] Triggering background auto-sync for {conn.connection_id} (interval: {interval_m}m)...")
                            asyncio.create_task(self.start_sync_job(conn.connection_id, trigger_type=CalendarTriggerType.AUTO_SYNC))
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[CalendarSyncManager] Error in auto-sync scheduler loop: {e}")

    async def purge_all_connector_data(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        store_res = self.store.purge_all_synced_data(tenant_id=conn.tenant_id, user_id=conn.user_id)

        vectors_deleted = 0
        try:
            vectors_deleted = self.queue_worker.ingestion_pipeline.vector_store.delete_by_tenant_source_user(
                tenant_id=tenant_id, source="google_calendar", user_id=user_id
            )
        except Exception as e:
            try:
                from module_3_batch_ingestion_vector.vector_store import VectorStore
                vs = VectorStore()
                vectors_deleted = vs.delete_by_tenant_source_user(tenant_id=tenant_id, source="google_calendar", user_id=user_id)
            except Exception:
                pass

        docs_purged = 0
        try:
            docs_purged = self.queue_worker.store.purge_by_tenant_source_user(
                tenant_id=tenant_id, source="google_calendar", user_id=user_id
            )
        except Exception as e:
            print(f"[CalendarSyncManager] Canonical doc deletion notice: {e}")

        return {
            "status": "success",
            "message": f"Purged all Google Calendar data for user {user_id}.",
            "purged_metrics": {
                "synced_events_deleted": store_res.get("events_deleted", 0),
                "activities_deleted": store_res.get("activities_deleted", 0),
                "vectors_deleted": vectors_deleted,
                "canonical_docs_deleted": docs_purged,
            },
        }

