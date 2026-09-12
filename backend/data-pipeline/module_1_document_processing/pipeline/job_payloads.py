"""Turning ingestion work into queue payloads, and back.

Two things need care when a job stops being a live Python object:

* ``CanonicalEvent`` holds an enum and a datetime, neither of which is JSON.
* The bytes of an uploaded or connector-fetched file can be tens of megabytes.
  Those must not go through Redis. They are written to the raw object store
  first - which is also what makes the upload itself durable, since the bytes
  previously existed only in the request handler's memory until parsing ran -
  and the payload carries only the storage reference.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from module_1_document_processing.composio_connector.events.canonical_event import (
    CanonicalEvent,
    EventType,
)
from module_1_document_processing.raw_object_store import raw_object_store

STAGING_PREFIX = "staging"
JOB_CONNECTOR_EVENT = "connector_event"
JOB_DOCUMENT_INGEST = "document_ingest"


def stage_bytes(tenant_id: str, doc_id: str, data: bytes, content_type: str = "") -> Optional[str]:
    """Persist job bytes and return a storage reference the worker can read back."""
    if not data:
        return None
    key = f"{tenant_id or 'unknown'}/{STAGING_PREFIX}/{doc_id or uuid.uuid4().hex}"
    return raw_object_store.put(key, data, content_type=content_type)


def load_staged_bytes(ref: str) -> Optional[bytes]:
    return raw_object_store.get(ref) if ref else None


def discard_staged_bytes(ref: str) -> None:
    """Drop a staged copy once the job has been processed."""
    if not ref:
        return
    try:
        raw_object_store.delete(ref)
    except Exception as err:
        print(f"[JobPayloads] Could not remove staged bytes {ref}: {err}")


def event_to_payload(event: CanonicalEvent) -> dict[str, Any]:
    """JSON-safe payload for a connector event, with any inline bytes offloaded."""
    metadata = dict(event.metadata or {})
    raw_bytes = metadata.pop("raw_bytes", None)
    staged_ref = ""
    if isinstance(raw_bytes, (bytes, bytearray)):
        staged_ref = stage_bytes(
            event.tenant_id,
            f"{event.source}_{event.external_id}",
            bytes(raw_bytes),
            content_type=str(metadata.get("mime_type") or ""),
        ) or ""

    return {
        "event_id": event.event_id,
        "event_type": event.event_type.value if isinstance(event.event_type, EventType) else str(event.event_type),
        "source": event.source,
        "tenant_id": event.tenant_id,
        "user_id": event.user_id,
        "external_id": event.external_id,
        "raw_ref": event.raw_ref or {},
        "acl": list(event.acl or []),
        "timestamp": (event.timestamp or datetime.now(timezone.utc)).isoformat(),
        "metadata": metadata,
        "staged_ref": staged_ref,
    }


def payload_to_event(payload: dict[str, Any]) -> CanonicalEvent:
    """Rebuild the event, restoring offloaded bytes into ``metadata['raw_bytes']``."""
    metadata = dict(payload.get("metadata") or {})
    staged_ref = payload.get("staged_ref") or ""
    if staged_ref:
        data = load_staged_bytes(staged_ref)
        if data:
            metadata["raw_bytes"] = data
        else:
            print(f"[JobPayloads] Staged bytes missing for {staged_ref}; continuing without them.")

    raw_timestamp = payload.get("timestamp")
    try:
        timestamp = datetime.fromisoformat(raw_timestamp) if raw_timestamp else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        timestamp = datetime.now(timezone.utc)

    try:
        event_type = EventType(payload.get("event_type") or EventType.CREATE.value)
    except ValueError:
        event_type = EventType.CREATE

    return CanonicalEvent(
        event_id=payload.get("event_id") or f"evt_{uuid.uuid4().hex[:12]}",
        event_type=event_type,
        source=payload.get("source") or "",
        tenant_id=payload.get("tenant_id") or "",
        user_id=payload.get("user_id") or "",
        external_id=payload.get("external_id") or "",
        raw_ref=payload.get("raw_ref") or {},
        acl=list(payload.get("acl") or []),
        timestamp=timestamp,
        metadata=metadata,
    )
