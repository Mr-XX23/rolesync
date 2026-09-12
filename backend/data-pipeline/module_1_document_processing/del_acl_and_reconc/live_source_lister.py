"""Re-lists what actually exists at a connected source, for reconciliation.

Composio triggers are create/update oriented: providers do not reliably emit
delete or permission-change events ("because webhooks lie" - doc/arch.md). The
only dependable way to catch a missed deletion or ACL drift is to periodically
re-list the source and diff it against the canonical store.

SAFETY: every listing carries a `complete` flag. If a call fails, is truncated,
or the source cannot be exhaustively listed, `complete` is False and the sweeper
MUST NOT infer deletions from it - otherwise one failed API call would tombstone
a tenant's entire corpus.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

# Sources whose contents are a bounded, listable set. Mailboxes and chat
# histories are unbounded streams: a partial page says nothing about deletion,
# so they are never swept for tombstones.
SWEEPABLE_SOURCES = ("gdrive", "notion", "calendar")
UNSWEEPABLE_REASON = (
    "source is an unbounded message stream; a partial listing cannot prove deletion"
)


def _max_pages() -> int:
    try:
        return max(1, int(os.environ.get("RECONCILIATION_MAX_PAGES", "10")))
    except (TypeError, ValueError):
        return 10


@dataclass
class LiveListing:
    """What the source currently holds. `complete=False` disables deletion inference."""

    source: str
    items: list[dict[str, Any]] = field(default_factory=list)
    complete: bool = False
    reason: str = ""

    @property
    def external_ids(self) -> set[str]:
        return {str(item.get("external_id")) for item in self.items if item.get("external_id")}


class LiveSourceLister:
    """Lists live external ids (and ACLs where the provider returns them)."""

    def __init__(self, composio_client: Any) -> None:
        self.composio = composio_client

    # ---- helpers ---------------------------------------------------------
    def _execute(self, slug: str, arguments: dict[str, Any], user_id: str) -> Optional[dict[str, Any]]:
        try:
            res = self.composio._composio.tools.execute(
                slug=slug,
                arguments=arguments,
                user_id=user_id,
                dangerously_skip_version_check=True,
            )
            data = res.get("data", {}) if isinstance(res, dict) else getattr(res, "data", {})
            return data if isinstance(data, dict) else None
        except Exception as err:
            print(f"[LiveSourceLister] {slug} failed for user_id={user_id}: {err}")
            return None

    @staticmethod
    def _unwrap(data: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
            nested = data.get("data")
            if isinstance(nested, dict) and isinstance(nested.get(key), list):
                return nested[key]
        return []

    # ---- per-source listings --------------------------------------------
    def list_source(self, source: str, user_id: str) -> LiveListing:
        key = (source or "").lower()
        if key not in SWEEPABLE_SOURCES:
            return LiveListing(source=key, complete=False, reason=UNSWEEPABLE_REASON)

        if key == "gdrive":
            return self._list_gdrive(user_id)
        if key == "notion":
            return self._list_notion(user_id)
        return self._list_calendar(user_id)

    def _list_gdrive(self, user_id: str) -> LiveListing:
        items: list[dict[str, Any]] = []
        page_token: Optional[str] = None
        for _ in range(_max_pages()):
            args: dict[str, Any] = {
                "pageSize": 1000,
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            }
            if page_token:
                args["pageToken"] = page_token

            data = self._execute("GOOGLEDRIVE_LIST_FILES", args, user_id)
            if data is None:
                return LiveListing(source="gdrive", complete=False, reason="listing call failed")

            files = self._unwrap(data, "files")
            for entry in files:
                if not isinstance(entry, dict) or not entry.get("id"):
                    continue
                item: dict[str, Any] = {"external_id": str(entry["id"])}
                # Only carry acl when the provider actually returned permissions -
                # a missing field must not be read as "no one has access".
                permissions = entry.get("permissions")
                if isinstance(permissions, list):
                    item["acl"] = [
                        str(p.get("emailAddress") or p.get("id"))
                        for p in permissions
                        if isinstance(p, dict) and (p.get("emailAddress") or p.get("id"))
                    ]
                items.append(item)

            nested = data.get("data") if isinstance(data.get("data"), dict) else {}
            page_token = data.get("nextPageToken") or (nested.get("nextPageToken") if nested else None)
            if not page_token:
                return LiveListing(source="gdrive", items=items, complete=True)

        return LiveListing(source="gdrive", items=items, complete=False, reason="listing truncated at page cap")

    def _list_notion(self, user_id: str) -> LiveListing:
        data = self._execute("NOTION_SEARCH_NOTION_PAGE", {"page_size": 100}, user_id)
        if data is None:
            return LiveListing(source="notion", complete=False, reason="listing call failed")

        results = self._unwrap(data, "results", "pages")
        items = [
            {"external_id": str(entry["id"])}
            for entry in results
            if isinstance(entry, dict) and entry.get("id")
        ]
        nested = data.get("data") if isinstance(data.get("data"), dict) else {}
        has_more = bool(data.get("has_more") or (nested.get("has_more") if nested else False))
        if has_more:
            return LiveListing(source="notion", items=items, complete=False, reason="listing truncated (has_more)")
        return LiveListing(source="notion", items=items, complete=True)

    def _list_calendar(self, user_id: str) -> LiveListing:
        for slug in ("GOOGLECALENDAR_LIST_EVENTS", "GOOGLECALENDAR_EVENTS_LIST", "GOOGLECALENDAR_FIND_EVENT"):
            data = self._execute(slug, {"maxResults": 250, "singleEvents": True}, user_id)
            if data is None:
                continue
            events = self._unwrap(data, "items", "events")
            items = [
                {"external_id": str(entry["id"])}
                for entry in events
                if isinstance(entry, dict) and entry.get("id")
            ]
            nested = data.get("data") if isinstance(data.get("data"), dict) else {}
            next_token = data.get("nextPageToken") or (nested.get("nextPageToken") if nested else None)
            if next_token:
                return LiveListing(source="calendar", items=items, complete=False, reason="listing truncated")
            return LiveListing(source="calendar", items=items, complete=True)

        return LiveListing(source="calendar", complete=False, reason="listing call failed")
