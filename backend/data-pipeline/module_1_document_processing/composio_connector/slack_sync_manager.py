import asyncio
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.composio_connector.composio_client import ComposioClient
from module_1_document_processing.composio_connector.normalizers.slack_normalizer import normalize_slack
from module_1_document_processing.composio_connector.date_utils import normalize_to_utc
from module_1_document_processing.composio_connector.slack_models import (
    SlackConnection,
    SlackSyncStatus,
    SlackSyncConfig,
    SlackBackfillState,
    SlackLockState,
    SyncedSlackMessageRecord,
    SlackSyncActivity,
    SlackActivityItem,
    SlackTriggerType,
    HistoricalSyncStatus,
)
from module_1_document_processing.composio_connector.slack_store import SlackStore
from module_1_document_processing.pipeline.queue_worker import QueueWorker
from module_1_document_processing.composio_connector.rate_limiter import global_rate_limiter
from module_1_document_processing.composio_connector.error_classifier import classify_error, ConnectorAction, ConnectorErrorType

class SlackSyncManager:
    """Core synchronization manager orchestrating Slack DMs, Group Messages, Channels, Threads, Locking, and Scheduler."""

    def __init__(
        self,
        store: SlackStore | None = None,
        composio: ComposioClient | None = None,
        queue_worker: QueueWorker | None = None,
    ) -> None:
        self.store = store or SlackStore()
        self.composio = composio or ComposioClient()
        self.queue_worker = queue_worker or QueueWorker()
        self.auto_sync_interval_minutes = int(os.environ.get("SLACK_AUTO_SYNC_INTERVAL", "30"))
        self._scheduler_task: asyncio.Task | None = None
        self._scheduler_running = False
        self._last_auto_sync_times: dict[str, datetime] = {}

    async def start_scheduler(self) -> None:
        if self._scheduler_running:
            return
        self._scheduler_running = True
        self._scheduler_task = asyncio.create_task(self._auto_sync_cron_loop())
        print(f"[SlackSyncManager] Auto-sync scheduler running (interval: {self.auto_sync_interval_minutes}m).")

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
        print("[SlackSyncManager] Background auto-sync scheduler stopped.")

    def get_connection_status(self, user_id: str, tenant_id: str = "tenant_default") -> SlackConnection:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        is_connected = self.composio.is_account_connected(user_id, "slack")

        synced_count = self.store.count_synced_messages(conn.tenant_id, conn.connection_id)
        changed = False
        if conn.backfill_state.total_synced_so_far != synced_count:
            conn.backfill_state.total_synced_so_far = synced_count
            changed = True

        old_status = conn.status
        old_progress = conn.current_progress

        if is_connected:
            if conn.status in (SlackSyncStatus.AVAILABLE, SlackSyncStatus.DISCONNECTED, SlackSyncStatus.CONFIGURATION_REQUIRED):
                if synced_count > 0 or conn.last_successful_sync_at is not None or conn.backfill_state.historical_sync_status == HistoricalSyncStatus.COMPLETED:
                    if conn.backfill_state.historical_sync_status == HistoricalSyncStatus.COMPLETED:
                        conn.status = SlackSyncStatus.UP_TO_DATE
                        if not conn.current_progress or conn.current_progress.lower().startswith("error"):
                            conn.current_progress = "Up to date"
                    elif getattr(conn.config, "auto_sync_enabled", False) and conn.config.sync_frequency not in ("off", "manual") and (conn.config.auto_sync_interval_minutes or 0) > 0:
                        conn.status = SlackSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC
                        if not conn.current_progress:
                            conn.current_progress = f"Next sync in {conn.config.auto_sync_interval_minutes}m"
                    else:
                        conn.status = SlackSyncStatus.CONNECTED
                        if not conn.current_progress:
                            conn.current_progress = "Sync completed"
                elif conn.status in (SlackSyncStatus.AVAILABLE, SlackSyncStatus.DISCONNECTED):
                    conn.status = SlackSyncStatus.CONFIGURATION_REQUIRED
        else:
            if conn.status in (SlackSyncStatus.CONFIGURATION_REQUIRED, SlackSyncStatus.CONNECTED, SlackSyncStatus.SYNCING, SlackSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC, SlackSyncStatus.UP_TO_DATE, SlackSyncStatus.PARTIAL_SUCCESS):
                conn.status = SlackSyncStatus.AVAILABLE

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
        redirect_url = self.composio.initiate_user_connection(user_id=user_id, source="slack", callback_url=callback_url)
        trigger_id = None
        if getattr(conn.config, "webhook_enabled", False):
            trigger_id = self.composio.enable_trigger(trigger_slug=ComposioClient.SLACK_NEW_MESSAGE, user_id=user_id)
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
                "message": "Cannot modify configuration while Slack synchronization is actively in progress.",
                "is_locked": True,
            }

        if config_data:
            max_msgs = int(config_data.get("max_messages_per_sync", config_data.get("max_items_per_sync", conn.config.max_messages_per_sync)))
            conn.config.max_messages_per_sync = max(1, min(30, max_msgs))
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

            synced_count = self.store.count_synced_messages(conn.tenant_id, conn.connection_id)
            if synced_count == 0:
                conn.backfill_state.historical_sync_status = HistoricalSyncStatus.NOT_STARTED
                conn.backfill_state.is_backfill_complete = False
                conn.backfill_state.historical_sync_cursor = None
                conn.backfill_state.next_page_token = None

        conn.status = SlackSyncStatus.SYNCING
        now = datetime.now(timezone.utc)
        conn.last_successful_sync_at = now
        self._last_auto_sync_times[conn.connection_id] = now
        self.store.update_connection(conn)

        asyncio.create_task(self.execute_sync_job(conn.connection_id, trigger_type=SlackTriggerType.INITIAL_SYNC))

        return {
            "status": "success",
            "message": "Slack configuration saved. Initial synchronization has started.",
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
                        trigger_slug=ComposioClient.SLACK_NEW_MESSAGE, user_id=user_id
                    )
            else:
                if conn.webhook_trigger_id:
                    self.composio.disable_trigger(conn.webhook_trigger_id)
                    conn.webhook_trigger_id = None
        except Exception as trig_err:
            print(f"[SlackSyncManager] Webhook trigger toggle notice: {trig_err}")

        if not conn.config.auto_sync_enabled or conn.config.sync_frequency in ("off", "manual"):
            if conn.status == SlackSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC:
                conn.status = SlackSyncStatus.CONNECTED
                conn.current_progress = "Auto-sync disabled (Manual only)"
        elif conn.status == SlackSyncStatus.CONNECTED:
            conn.status = SlackSyncStatus.WAITING_FOR_NEXT_AUTO_SYNC
            conn.current_progress = f"Next sync in {conn.config.auto_sync_interval_minutes}m"

        self.store.update_connection(conn)
        self._last_auto_sync_times[conn.connection_id] = datetime.now(timezone.utc)

        return {
            "status": "success",
            "message": f"Slack Auto-Sync schedule updated to {sync_frequency}.",
            "sync_frequency": conn.config.sync_frequency,
            "auto_sync_interval_minutes": conn.config.auto_sync_interval_minutes,
            "auto_sync_enabled": conn.config.auto_sync_enabled,
            "webhook_enabled": conn.config.webhook_enabled,
            "connection": conn.to_dict(),
        }

    async def trigger_manual_sync(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)

        if conn.status == SlackSyncStatus.DISCONNECTED:
            return {"status": "error", "message": "Connection is disconnected. Reconnect Slack to resume sync."}

        job_id = f"job_manual_{uuid.uuid4().hex[:8]}"
        if not self.store.acquire_lock(conn.connection_id, job_id=job_id):
            return {
                "status": "locked",
                "message": "Your Slack data is currently being processed. Please wait a moment before starting another sync.",
                "is_locked": True,
            }

        self.store.release_lock(conn.connection_id, job_id=job_id)
        asyncio.create_task(self.execute_sync_job(conn.connection_id, trigger_type=SlackTriggerType.MANUAL_SYNC))

        return {
            "status": "success",
            "message": "Slack manual synchronization initiated.",
            "connection_id": conn.connection_id,
        }

    async def trigger_resync(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)

        if conn.status == SlackSyncStatus.DISCONNECTED:
            return {"status": "error", "message": "Connection is disconnected. Reconnect Slack to resync."}

        job_id = f"job_resync_{uuid.uuid4().hex[:8]}"
        if not self.store.acquire_lock(conn.connection_id, job_id=job_id):
            return {
                "status": "locked",
                "message": "Your Slack data is currently being processed. Please wait a moment before starting another sync.",
                "is_locked": True,
            }

        self.store.release_lock(conn.connection_id, job_id=job_id)
        asyncio.create_task(self.execute_sync_job(conn.connection_id, trigger_type=SlackTriggerType.RESYNC, is_resync=True))

        return {
            "status": "success",
            "message": "Slack resync initiated. Skipping already indexed messages and syncing missing correspondence.",
            "connection_id": conn.connection_id,
        }

    async def retry_failed_items(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        """Collects recently failed Slack messages and triggers a targeted recovery sync."""
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        failed_items = self.store.get_failed_items(conn.connection_id)
        if not failed_items:
            return {
                "status": "success",
                "message": "No failed Slack messages found to retry.",
                "retried_count": 0,
            }
        return await self.trigger_resync(user_id=user_id, tenant_id=tenant_id)

    def disconnect_connection(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        try:
            self.composio.disconnect_user_account(user_id=user_id, source="slack")
        except Exception as e:
            print(f"[SlackSyncManager] Composio token revocation notice: {e}")

        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        conn.status = SlackSyncStatus.DISCONNECTED
        conn.lock.is_locked = False
        conn.lock.locked_by_job_id = None
        conn.current_progress = ""
        conn.webhook_trigger_id = None
        conn.last_successful_sync_at = None
        self.store.release_lock(conn.connection_id, "")
        self._last_auto_sync_times.pop(conn.connection_id, None)
        self.store.update_connection(conn)

        print(f"[SlackSyncManager] Disconnected Slack for user={user_id}. Vector memories preserved.")
        return {
            "status": "success",
            "message": "Slack disconnected. Backend OAuth tokens invalidated. Synced vector memories preserved.",
            "connection": conn.to_dict(),
        }

    async def execute_sync_job(
        self,
        connection_id: str,
        trigger_type: SlackTriggerType = SlackTriggerType.AUTO_SYNC,
        is_resync: bool = False,
    ) -> None:
        job_id = f"job_{trigger_type.value.lower()}_{uuid.uuid4().hex[:8]}"

        if not self.store.acquire_lock(connection_id=connection_id, job_id=job_id, lease_seconds=900):
            print(f"[SlackSyncManager] Job {job_id} could not acquire lock for {connection_id}. Aborting.")
            return

        self.store.start_heartbeat(connection_id=connection_id, job_id=job_id, lease_seconds=900)

        conn = self.store._connections.get(connection_id)
        if not conn:
            self.store.stop_heartbeat(connection_id)
            self.store.release_lock(connection_id, job_id)
            return

        conn.status = SlackSyncStatus.SYNCING
        conn.current_progress = ""
        self.store.update_connection(conn)

        activity = SlackSyncActivity(
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
            limit = conn.config.max_messages_per_sync  # default 15, max 30

            # 1. Discover messages from Slack (channels, DMs, MPIMs, threads)
            discovered_messages = self._fetch_eligible_slack_messages(conn, max_limit=limit, is_resync=is_resync)
            activity.metrics["total_discovered"] = len(discovered_messages)

            if not discovered_messages:
                print(f"[SlackSyncManager] No new unsynced messages found for {connection_id}.")
                conn.status = SlackSyncStatus.UP_TO_DATE
                conn.current_progress = "Up to date"
                conn.last_successful_sync_at = datetime.now(timezone.utc)
                self._last_auto_sync_times[conn.connection_id] = conn.last_successful_sync_at
                self.store.update_connection(conn)

                activity.status = "COMPLETED"
                activity.completed_at = datetime.now(timezone.utc)
                self.store.record_activity(activity)
                self.store.release_lock(connection_id, job_id)
                return

            # 2. Parallel sub-batching 5 messages at a time
            sub_batch_size = 5
            total_items = len(discovered_messages)

            for i in range(0, total_items, sub_batch_size):
                sub_batch = discovered_messages[i : i + sub_batch_size]
                tasks = [
                    self._process_single_message_item(conn, item, is_resync=is_resync)
                    for item in sub_batch
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for r in results:
                    activity.metrics["processed"] += 1
                    if isinstance(r, Exception):
                        activity.metrics["failed"] += 1
                        activity.items.append({
                            "message_id": "unknown",
                            "name": "Processing error",
                            "subject": "Slack Processing Error",
                            "sender": "slack_sync",
                            "message_type": "unknown",
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
                conn.status = SlackSyncStatus.UP_TO_DATE
                conn.current_progress = "Up to date"
                activity.status = "COMPLETED"
            elif activity.metrics["succeeded"] > 0:
                conn.status = SlackSyncStatus.PARTIAL_SUCCESS
                conn.current_progress = "Partial Success"
                activity.status = "PARTIAL_SUCCESS"
            else:
                conn.status = SlackSyncStatus.FAILED
                conn.current_progress = "Sync Failed"
                activity.status = "FAILED"

            activity.completed_at = datetime.now(timezone.utc)
            conn.backfill_state.total_synced_so_far = self.store.count_synced_messages(conn.tenant_id, conn.connection_id)
            self.store.update_connection(conn)
            self.store.record_activity(activity)

        except Exception as e:
            err_type, sanitized_msg, action = classify_error(e)
            print(f"[SlackSyncManager] Error in sync job {job_id}: {sanitized_msg} (type={err_type})")
            if action == ConnectorAction.RECONNECT:
                conn.status = SlackSyncStatus.CONFIGURATION_REQUIRED
                conn.current_progress = "Access token expired. Reconnection required."
            else:
                conn.status = SlackSyncStatus.FAILED
                conn.current_progress = f"Error: {sanitized_msg[:120]}"
            self.store.update_connection(conn)
            activity.status = "FAILED"
            activity.completed_at = datetime.now(timezone.utc)
            self.store.record_activity(activity)
        finally:
            self.store.stop_heartbeat(connection_id)
            self.store.release_lock(connection_id, job_id)

    def _fetch_eligible_slack_messages(
        self,
        conn: SlackConnection,
        max_limit: int = 15,
        is_resync: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Discovers Slack messages across Channels, Direct Messages, Group Messages, and Threads.
        """
        user_id = conn.user_id
        if not self.composio or not getattr(self.composio, "_composio", None):
            print(f"[SlackSyncManager] Composio SDK not active. Returning mock/test fixtures.")
            return []

        categories = conn.config.categories or ["PUBLIC_CHANNELS", "DIRECT_MESSAGES", "GROUP_MESSAGES"]
        cat_set = {c.upper() for c in categories}
        include_all = "ALL" in cat_set

        # Determine conversation types to query
        types_list = []
        if include_all or "PUBLIC_CHANNELS" in cat_set:
            types_list.append("public_channel")
        if include_all or "PRIVATE_CHANNELS" in cat_set:
            types_list.append("private_channel")
        if include_all or "DIRECT_MESSAGES" in cat_set or "DM" in cat_set:
            types_list.append("im")
        if include_all or "GROUP_MESSAGES" in cat_set or "MPIM" in cat_set:
            types_list.append("mpim")

        if not types_list:
            types_list = ["public_channel", "private_channel", "im", "mpim"]

        types_str = ",".join(types_list)
        channels = self._list_slack_conversations(user_id, types=types_str)
        collected_messages: list[dict[str, Any]] = []

        # Partition into DMs/group chats and public/private channels so DMs are never starved out
        dm_conversations = [c for c in channels if c.get("is_im") or str(c.get("id", "")).startswith("D") or c.get("is_mpim") or str(c.get("id", "")).startswith("G")]
        channel_conversations = [c for c in channels if c not in dm_conversations]

        # Prioritize querying active conversations proportionally
        ordered_targets = []
        # Alternate between DMs and channels to ensure both get indexed within max_limit
        max_len = max(len(dm_conversations), len(channel_conversations))
        for i in range(max_len):
            if i < len(dm_conversations):
                ordered_targets.append(dm_conversations[i])
            if i < len(channel_conversations):
                ordered_targets.append(channel_conversations[i])

        per_conv_limit = max(3, max_limit // max(1, len(ordered_targets)))

        for ch in ordered_targets:
            if len(collected_messages) >= max_limit:
                break
            ch_id = ch.get("id") or ch.get("channel_id")
            ch_name = ch.get("name") or ch.get("user") or ch_id
            if not ch_id:
                continue

            # Fetch channel / DM history (fetch at least 20 recent messages so unsynced older messages/attachments are reached)
            remaining = max_limit - len(collected_messages)
            msgs = self._fetch_conversation_history(user_id, ch_id, limit=max(20, remaining))
            for m in msgs:
                if len(collected_messages) >= max_limit:
                    break
                ts = m.get("ts") or m.get("event_ts")
                if not ts:
                    continue

                msg_id = f"{ch_id}:{ts}"
                if not is_resync and self.store.is_message_synced(conn.tenant_id, conn.connection_id, msg_id):
                    continue

                m["_channel_id"] = ch_id
                m["_channel_name"] = ch_name
                m["_message_type"] = "im" if (ch.get("is_im") or str(ch_id).startswith("D")) else ("mpim" if (ch.get("is_mpim") or str(ch_id).startswith("G")) else ("private_channel" if ch.get("is_private") else "public_channel"))
                collected_messages.append(m)

        return collected_messages[:max_limit]

    def _get_slack_connected_account_id(self, user_id: str) -> str | None:
        """Helper to find the active connected_account_id for Slack under this user."""
        if not self.composio or not getattr(self.composio, "_composio", None):
            return None
        try:
            accs = self.composio._composio.connected_accounts.list(user_ids=[user_id])
            items = getattr(accs, "items", accs)
            for a in items:
                toolkit_str = str(getattr(a, "appUniqueId", None) or getattr(a, "toolkit", None) or "")
                if "slack" in toolkit_str.lower():
                    acc_id = getattr(a, "id", None) or (a.get("id") if isinstance(a, dict) else None)
                    if acc_id:
                        return str(acc_id)
        except Exception as err:
            print(f"[SlackSyncManager] Could not determine connected account ID for user {user_id}: {err}")
        return None

    def _download_slack_file_bytes(self, user_id: str, file_url: str, connected_account_id: str | None = None) -> bytes | None:
        """Downloads Slack private file bytes using Composio tool proxy."""
        if not file_url:
            return None
        if not connected_account_id:
            connected_account_id = self._get_slack_connected_account_id(user_id)
        if not connected_account_id:
            return None

        try:
            import urllib.request
            res = self.composio._composio.tools.proxy(
                endpoint=file_url,
                method="GET",
                connected_account_id=connected_account_id,
            )
            download_url = None
            if hasattr(res, "binary_data") and res.binary_data and getattr(res.binary_data, "url", None):
                download_url = res.binary_data.url
            elif isinstance(res, dict) and res.get("binary_data", {}).get("url"):
                download_url = res["binary_data"]["url"]

            if download_url:
                req = urllib.request.Request(download_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.read()
            elif hasattr(res, "data") and isinstance(res.data, bytes):
                return res.data
        except Exception as dl_err:
            print(f"[SlackSyncManager] Failed downloading Slack file from {file_url}: {dl_err}")
        return None

    def _list_slack_conversations(self, user_id: str, types: str = "public_channel,private_channel,im,mpim") -> list[dict[str, Any]]:
        """Lists Slack conversations including DMs, group DMs, and channels using Composio tools."""
        tool_slugs = ["SLACK_LIST_CONVERSATIONS", "SLACK_LIST_ALL_CHANNELS", "SLACK_FIND_CHANNELS"]
        for slug in tool_slugs:
            try:
                res = self.composio._composio.tools.execute(
                    slug=slug,
                    arguments={"types": types, "limit": 50},
                    user_id=user_id,
                    dangerously_skip_version_check=True,
                )
                data = res.get("data", {}) if isinstance(res, dict) else getattr(res, "data", {})
                if isinstance(data, dict):
                    channels = data.get("channels") or data.get("data", {}).get("channels") or []
                    if channels:
                        return channels
            except Exception as e:
                print(f"[SlackSyncManager] Failed listing conversations via {slug}: {e}")
        return []

    def _fetch_conversation_history(self, user_id: str, channel_id: str, limit: int = 15) -> list[dict[str, Any]]:
        """Fetches messages for a channel, DM, or group chat using Composio tools."""
        tool_slugs = ["SLACK_FETCH_CONVERSATION_HISTORY", "SLACK_FETCH_MESSAGE_THREAD_FROM_A_CONVERSATION"]
        for slug in tool_slugs:
            try:
                res = self.composio._composio.tools.execute(
                    slug=slug,
                    arguments={"channel": channel_id, "limit": min(limit, 30)},
                    user_id=user_id,
                    dangerously_skip_version_check=True,
                )
                data = res.get("data", {}) if isinstance(res, dict) else getattr(res, "data", {})
                if isinstance(data, dict):
                    messages = data.get("messages") or data.get("data", {}).get("messages") or []
                    if messages:
                        return messages
            except Exception as e:
                print(f"[SlackSyncManager] Failed fetching history for {channel_id} via {slug}: {e}")
        return []

    async def _process_single_message_item(
        self,
        conn: SlackConnection,
        item: dict[str, Any],
        is_resync: bool = False,
    ) -> dict[str, Any]:
        """Ingests a single Slack message into the vector pipeline with deduplication and audit tracking."""
        ch_id = item.get("_channel_id") or item.get("channel") or item.get("channel_id") or "general"
        ch_name = item.get("_channel_name") or item.get("channel_name") or ch_id
        ts = str(item.get("ts") or item.get("event_ts") or "")
        msg_id = f"{ch_id}:{ts}"
        sender_id = item.get("user") or item.get("user_id") or "unknown_user"
        sender_name = item.get("user_name") or item.get("username") or sender_id
        text = item.get("text") or ""
        msg_type = item.get("_message_type") or "public_channel"

        if not is_resync and self.store.is_message_synced(conn.tenant_id, conn.connection_id, msg_id):
            return {
                "message_id": msg_id,
                "channel_id": ch_id,
                "channel_name": ch_name,
                "sender_name": sender_name,
                "name": f"#{ch_name}: {text[:60]}",
                "subject": f"#{ch_name} - {sender_name}",
                "sender": sender_name,
                "message_type": msg_type,
                "status": "SKIPPED",
                "error_message": "Already indexed in vector memory",
            }

        await global_rate_limiter.acquire("slack")

        # Process file attachments and download private file bytes if present
        raw_files = item.get("files", [])
        enriched_files = []
        for f in raw_files:
            if isinstance(f, dict):
                f_copy = dict(f)
                file_url = f.get("url_private_download") or f.get("url_private")
                if file_url and not f_copy.get("raw_bytes"):
                    # Attempt download via Composio proxy
                    file_bytes = self._download_slack_file_bytes(conn.user_id, file_url)
                    if file_bytes:
                        f_copy["raw_bytes"] = file_bytes
                enriched_files.append(f_copy)

        # Format CanonicalEvent
        payload = {
            "metadata": {
                "user_id": conn.user_id,
                "channel_id": ch_id,
                "channel_name": ch_name,
                "trigger_slug": "SLACK_NEW_MESSAGE",
            },
            "data": {
                "channel": ch_id,
                "channel_name": ch_name,
                "user": sender_id,
                "user_name": sender_name,
                "ts": ts,
                "thread_ts": item.get("thread_ts"),
                "text": text,
                "files": enriched_files,
            }
        }
        canonical_event = normalize_slack(payload, tenant_id=conn.tenant_id)

        try:
            await self.queue_worker._process_event(canonical_event)

            # Record in store
            rec = SyncedSlackMessageRecord(
                doc_id=canonical_event.event_id,
                tenant_id=conn.tenant_id,
                connection_id=conn.connection_id,
                message_id=msg_id,
                channel_id=ch_id,
                channel_name=ch_name,
                message_type=msg_type,
                sender_id=sender_id,
                sender_name=sender_name,
                text=text,
                thread_ts=item.get("thread_ts"),
                received_at=canonical_event.timestamp,
                sync_status="SUCCESS",
                attachments=canonical_event.metadata.get("files", []),
                vector_chunk_count=1,
            )
            self.store.record_synced_message(rec)

            return {
                "message_id": msg_id,
                "channel_id": ch_id,
                "channel_name": ch_name,
                "sender_name": sender_name,
                "name": f"#{ch_name}: {text[:60]}",
                "subject": f"#{ch_name} - {sender_name}",
                "sender": sender_name,
                "message_type": msg_type,
                "status": "SUCCESS",
                "error_message": None,
                "thread_ts": item.get("thread_ts"),
            }
        except Exception as err:
            err_type, sanitized_err, _ = classify_error(err)
            return {
                "message_id": msg_id,
                "channel_id": ch_id,
                "channel_name": ch_name,
                "sender_name": sender_name,
                "name": f"#{ch_name}: {text[:60]}",
                "subject": f"#{ch_name} - {sender_name}",
                "sender": sender_name,
                "message_type": msg_type,
                "status": "FAILED",
                "error_message": sanitized_err,
                "thread_ts": item.get("thread_ts"),
            }

    async def process_webhook_event(
        self,
        event: CanonicalEvent,
        raw_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Processes real-time Slack webhook events from Composio."""
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

        # Crucial: align event tenant and user with the matched connection so everything indexes and displays correctly
        event.tenant_id = conn.tenant_id
        event.user_id = conn.user_id

        msg_id = event.external_id
        if self.store.is_message_synced(event.tenant_id, conn.connection_id, msg_id):
            return {"status": "ignored", "reason": "Slack message already synced"}

        # If webhook event has file attachments without raw_bytes, attempt download via Composio proxy
        files = event.metadata.get("files", [])
        if files and isinstance(files, list):
            for f in files:
                if isinstance(f, dict) and not f.get("raw_bytes"):
                    file_url = f.get("url_private_download") or f.get("url_private") or f.get("url")
                    if file_url:
                        f_bytes = self._download_slack_file_bytes(conn.user_id, file_url)
                        if f_bytes:
                            f["raw_bytes"] = f_bytes

        await self.queue_worker._process_event(event)

        ch_id = event.metadata.get("channel_id", "general")
        ch_name = event.metadata.get("channel_name", ch_id)
        sender_name = event.metadata.get("sender_name") or event.metadata.get("sender_id") or "slack_user"
        sender_id = event.metadata.get("sender_id") or "slack_user"
        text = event.metadata.get("text", "")

        rec = SyncedSlackMessageRecord(
            doc_id=event.event_id,
            tenant_id=event.tenant_id,
            connection_id=conn.connection_id,
            message_id=msg_id,
            channel_id=ch_id,
            channel_name=ch_name,
            message_type=event.metadata.get("message_type", "public_channel"),
            sender_id=sender_id,
            sender_name=sender_name,
            text=text,
            thread_ts=event.metadata.get("thread_ts"),
            received_at=event.timestamp,
            sync_status="SUCCESS",
            attachments=event.metadata.get("files", []),
            vector_chunk_count=1,
        )
        self.store.record_synced_message(rec)

        activity = SlackSyncActivity(
            activity_id=f"act_wh_{uuid.uuid4().hex[:8]}",
            job_id=f"job_wh_{uuid.uuid4().hex[:8]}",
            connection_id=conn.connection_id,
            tenant_id=conn.tenant_id,
            trigger_type=SlackTriggerType.WEBHOOK,
            status="COMPLETED",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            metrics={"total_discovered": 1, "processed": 1, "succeeded": 1, "skipped": 0, "failed": 0},
            items=[{
                "message_id": msg_id,
                "channel_id": ch_id,
                "channel_name": ch_name,
                "sender_name": sender_name,
                "name": f"#{ch_name}: {text[:60]}",
                "subject": f"#{ch_name} - {sender_name}",
                "sender": sender_name,
                "message_type": event.metadata.get("message_type", "public_channel"),
                "status": "SUCCESS",
                "error_message": None,
                "thread_ts": event.metadata.get("thread_ts"),
            }],
        )
        self.store.record_activity(activity)

        conn.last_successful_sync_at = datetime.now(timezone.utc)
        conn.backfill_state.total_synced_so_far = self.store.count_synced_messages(conn.tenant_id, conn.connection_id)
        self.store.update_connection(conn)

        return {"status": "success", "event_id": event.event_id, "message_id": msg_id}

    def get_data_summary(self, user_id: str, tenant_id: str = "tenant_default") -> dict[str, Any]:
        conn = self.store.get_or_create_connection(tenant_id=tenant_id, user_id=user_id)
        synced_count = self.store.count_synced_messages(tenant_id, conn.connection_id)
        acts = self.store.get_activities(conn.connection_id, limit=50)

        vector_count = 0
        try:
            vector_count = self.queue_worker.ingestion_pipeline.vector_store.count_vectors(
                tenant_id=tenant_id, source="slack", user_id=user_id
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
                tenant_id=tenant_id, source="slack", user_id=user_id
            )
        except Exception as e:
            print(f"[SlackSyncManager] Vector deletion error: {e}")

        docs_purged = 0
        try:
            docs_purged = self.queue_worker.store.purge_by_tenant_source_user(
                tenant_id=tenant_id, source="slack", user_id=user_id
            )
        except Exception as e:
            print(f"[SlackSyncManager] Canonical docs purge error: {e}")

        conn.backfill_state = SlackBackfillState()
        conn.current_progress = ""
        conn.last_successful_sync_at = None
        conn.status = SlackSyncStatus.CONFIGURATION_REQUIRED
        self.store.update_connection(conn)

        return {
            "status": "success",
            "message": "Slack connector data, vector embeddings, deduplication state, and activity logs have been purged.",
            "purged_metrics": {
                "synced_messages_deleted": purge_metrics.get("synced_messages_deleted", 0),
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
                            print(f"[SlackSyncManager] Triggering scheduled auto-sync for {conn.connection_id} (interval={interval_mins}m)...")
                            self._last_auto_sync_times[conn.connection_id] = now
                            asyncio.create_task(
                                self.execute_sync_job(conn.connection_id, trigger_type=SlackTriggerType.AUTO_SYNC)
                            )
            except asyncio.CancelledError:
                break
            except Exception as loop_err:
                print(f"[SlackSyncManager] Scheduler loop notice: {loop_err}")
                await asyncio.sleep(10)
