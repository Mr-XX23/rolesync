"""Schedules reconciliation sweeps across connected sources.

Deletions and permission changes are not delivered as Composio triggers, so the
canonical store is periodically reconciled against the live source instead.

Disabled by default: every sweep spends Composio tool executions (a billable
meter), so it must be switched on deliberately and runs daily when it is.

Config (env):
  RECONCILIATION_ENABLED           true to run on a schedule (default: false)
  RECONCILIATION_INTERVAL_MINUTES  sweep cadence (default: 1440 = daily)
  RECONCILIATION_MAX_DELETE_RATIO  refuse sweeps deleting more than this share (default: 0.5)
  RECONCILIATION_MAX_PAGES         page cap per source listing (default: 10)
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Optional

from module_1_document_processing.del_acl_and_reconc.live_source_lister import (
    SWEEPABLE_SOURCES,
    LiveSourceLister,
)
from module_1_document_processing.del_acl_and_reconc.reconciliation_sweeper import (
    ReconciliationSweeper,
    SweepReport,
)

_TRUTHY = {"1", "true", "yes", "on"}
# Checked often enough to react to config changes without busy-looping.
_TICK_SECONDS = 60


class ReconciliationScheduler:
    """Periodically diffs each connected source against the canonical store."""

    def __init__(
        self,
        providers: Optional[dict[str, Any]] = None,
        sweeper: Optional[ReconciliationSweeper] = None,
    ) -> None:
        # {source: sync_manager} - each manager exposes .store and .composio
        self.providers = providers or {}
        self.sweeper = sweeper or ReconciliationSweeper()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_sweep_at: Optional[datetime] = None

    # ---- config ----------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return os.environ.get("RECONCILIATION_ENABLED", "").strip().lower() in _TRUTHY

    @property
    def interval_minutes(self) -> int:
        try:
            value = int(os.environ.get("RECONCILIATION_INTERVAL_MINUTES", "") or 1440)
            return value if value > 0 else 1440
        except (TypeError, ValueError):
            return 1440

    @property
    def last_sweep_at(self) -> Optional[datetime]:
        return self._last_sweep_at

    # ---- lifecycle -------------------------------------------------------
    async def start_scheduler(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        state = "enabled" if self.enabled else "disabled (set RECONCILIATION_ENABLED=true)"
        print(f"[ReconciliationScheduler] Started - {state}, interval={self.interval_minutes}m.")

    async def stop_scheduler(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("[ReconciliationScheduler] Stopped.")

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(_TICK_SECONDS)
                if not self.enabled:
                    continue

                now = datetime.now(timezone.utc)
                if self._last_sweep_at is not None:
                    elapsed_minutes = (now - self._last_sweep_at).total_seconds() / 60
                    if elapsed_minutes < self.interval_minutes:
                        continue

                self._last_sweep_at = now
                # Composio's SDK is synchronous; keep it off the event loop.
                reports = await asyncio.to_thread(self.sweep_all)
                print(f"[ReconciliationScheduler] Scheduled sweep finished across {len(reports)} connection(s).")
            except asyncio.CancelledError:
                break
            except Exception as err:
                print(f"[ReconciliationScheduler] Sweep cycle error: {err}")

    # ---- sweeping --------------------------------------------------------
    def sweep_all(self, tenant_id: str = "", source_filter: str = "", user_id: str = "") -> list[SweepReport]:
        """Run a sweep now. Safe to call manually; returns one report per connection."""
        reports: list[SweepReport] = []

        for source, manager in self.providers.items():
            if source_filter and source != source_filter:
                continue
            if source not in SWEEPABLE_SOURCES:
                # Mailboxes / chat histories cannot be exhaustively listed, so a
                # missing item never proves deletion. Skipped by design.
                continue

            try:
                connections = manager.store.list_all_active_connections()
            except Exception as err:
                print(f"[ReconciliationScheduler] Could not list {source} connections: {err}")
                continue

            lister = LiveSourceLister(manager.composio)
            for conn in connections:
                if tenant_id and getattr(conn, "tenant_id", "") != tenant_id:
                    continue
                if user_id and getattr(conn, "user_id", "") != user_id:
                    continue

                try:
                    listing = lister.list_source(source, conn.user_id)
                    if not listing.complete and not listing.items:
                        print(
                            f"[ReconciliationScheduler] Skipping {source} for user={conn.user_id}: "
                            f"{listing.reason or 'no usable listing'}"
                        )
                        continue

                    reports.append(
                        self.sweeper.sweep_source(
                            tenant_id=conn.tenant_id,
                            source=source,
                            live_source_docs=listing.items,
                            complete=listing.complete,
                        )
                    )
                except Exception as err:
                    print(f"[ReconciliationScheduler] Sweep failed for {source}/{conn.user_id}: {err}")

        return reports


reconciliation_scheduler = ReconciliationScheduler()
