"""Conversation / rep / deal / account memory, and offloaded tool results (implementation-plan §6).

Memory content is JSON. Rep, account and deal memory hold a list of facts::

    {"name": "Acme Corp", "facts": [{"id", "text", "saved_at", "saved_by", "session_id"}]}

and conversation memory holds the running summary of a session's older turns::

    {"summary": "...", "through": 42, "method": "model" | "digest"}

Every write goes through ``MemoryStore.update`` (optimistic versioning, see ``locks``).
"""

from __future__ import annotations

import copy
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.context.locks import VersionConflict, with_optimistic_retry
from app.core.enums import MemoryScope
from app.db.models import ContextBlob, MemoryEntry

Mutation = Callable[[dict[str, Any]], dict[str, Any] | None]  # None: nothing to change


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    scope: MemoryScope
    key: str
    version: int
    content: dict[str, Any]
    updated_at: datetime | None
    written_by: UUID | None


class MemoryStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], *, versions_kept: int = 20) -> None:
        self._sm = sessionmaker
        self._versions_kept = max(2, versions_kept)

    async def latest(self, *, tenant_id: UUID, scope: MemoryScope, key: str) -> MemoryRecord | None:
        async with self._sm() as db:
            row = await db.scalar(
                select(MemoryEntry)
                .where(MemoryEntry.tenant_id == tenant_id, MemoryEntry.scope == scope, MemoryEntry.scope_key == key)
                .order_by(MemoryEntry.version.desc())
                .limit(1)
            )
        return _record(row) if row is not None else None

    async def list_latest(self, *, tenant_id: UUID, scope: MemoryScope, limit: int = 200) -> list[MemoryRecord]:
        """The latest version of every key in a scope, most recently changed first."""
        async with self._sm() as db:
            rows = await db.scalars(
                select(MemoryEntry)
                .where(MemoryEntry.tenant_id == tenant_id, MemoryEntry.scope == scope)
                .order_by(MemoryEntry.scope_key, MemoryEntry.version.desc())
                .distinct(MemoryEntry.scope_key)
            )
            records = [_record(row) for row in rows.all()]
        records.sort(key=lambda record: record.updated_at or datetime.min, reverse=True)
        return records[:limit]

    async def update(
        self, *, tenant_id: UUID, scope: MemoryScope, key: str, mutate: Mutation, written_by: UUID | None
    ) -> MemoryRecord | None:
        """Apply ``mutate`` to the latest content and store the result as the next version.

        ``mutate`` receives a private copy and may run more than once: when another writer
        stored the same version first, it is re-applied to their content (a merge)."""

        async def attempt() -> MemoryRecord | None:
            current = await self.latest(tenant_id=tenant_id, scope=scope, key=key)
            base = copy.deepcopy(current.content) if current is not None else {}
            changed = mutate(base)
            if changed is None or (current is not None and changed == current.content):
                return current
            version = (current.version if current is not None else 0) + 1
            row = MemoryEntry(
                tenant_id=tenant_id, scope=scope, scope_key=key, version=version, content=changed, written_by=written_by
            )
            try:
                async with self._sm.begin() as db:
                    db.add(row)
            except IntegrityError as exc:
                if "uq_memory_tenant_scope_key_version" in str(exc.orig):
                    raise VersionConflict(f"{scope}/{key} version {version}") from exc
                raise
            await self._prune(tenant_id=tenant_id, scope=scope, key=key, newest=version)
            return _record(row)

        return await with_optimistic_retry(attempt, attempts=25)

    async def _prune(self, *, tenant_id: UUID, scope: MemoryScope, key: str, newest: int) -> None:
        oldest_kept = newest - self._versions_kept + 1
        if oldest_kept <= 1:
            return
        async with self._sm.begin() as db:
            await db.execute(
                delete(MemoryEntry).where(
                    MemoryEntry.tenant_id == tenant_id,
                    MemoryEntry.scope == scope,
                    MemoryEntry.scope_key == key,
                    MemoryEntry.version < oldest_kept,
                )
            )


class BlobStore:
    """Tool results too large for the conversation, stored per session."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def put(self, *, tenant_id: UUID, session_id: UUID, call_id: str, tool: str, content: str) -> UUID:
        """Store once per (session, call); a repeat returns the existing reference."""
        stmt = (
            insert(ContextBlob)
            .values(id=uuid4(), tenant_id=tenant_id, session_id=session_id, call_id=call_id, tool=tool, content=content, chars=len(content))
            .on_conflict_do_nothing(constraint="uq_context_blob_session_call")
            .returning(ContextBlob.id)
        )
        async with self._sm.begin() as db:
            created = await db.scalar(stmt)
            if created is not None:
                return created
            existing = await db.scalar(
                select(ContextBlob.id).where(ContextBlob.session_id == session_id, ContextBlob.call_id == call_id)
            )
            assert existing is not None  # the conflict means the row exists
            return existing

    async def get(self, *, tenant_id: UUID, session_id: UUID, ref: UUID) -> ContextBlob | None:
        async with self._sm() as db:
            return await db.scalar(
                select(ContextBlob).where(
                    ContextBlob.id == ref, ContextBlob.tenant_id == tenant_id, ContextBlob.session_id == session_id
                )
            )


# ----------------------------------------------------------------------------- facts


def normalize_fact(text: str) -> str:
    """The comparison form of a fact: the same statement worded with other spacing or case is a duplicate."""
    return re.sub(r"\s+", " ", text).strip().strip(".!").lower()


def facts_of(content: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [fact for fact in (content or {}).get("facts") or [] if isinstance(fact, dict) and fact.get("id")]


def add_fact(
    content: dict[str, Any],
    text: str,
    *,
    saved_by: UUID | None,
    session_id: UUID | None,
    now: datetime,
    limit: int,
    name: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """(new content, the fact). New content is ``None`` when the fact was already known."""
    facts = facts_of(content)
    wanted = normalize_fact(text)
    for fact in facts:
        if normalize_fact(str(fact.get("text") or "")) == wanted:
            return (None if not name or content.get("name") == name else {**content, "name": name}), fact
    fact = {
        "id": f"f_{uuid4().hex[:12]}",
        "text": re.sub(r"\s+", " ", text).strip(),
        "saved_at": now.isoformat(),
        "saved_by": str(saved_by) if saved_by else None,
        "session_id": str(session_id) if session_id else None,
    }
    facts.append(fact)
    updated = {**content, "facts": facts[-limit:]}  # the oldest facts give way past the limit
    if name:
        updated["name"] = name
    return updated, fact


def remove_fact(content: dict[str, Any], fact_id: str) -> dict[str, Any] | None:
    facts = facts_of(content)
    kept = [fact for fact in facts if fact.get("id") != fact_id]
    return None if len(kept) == len(facts) else {**content, "facts": kept}


_LEGAL_SUFFIXES = frozenset(
    "inc incorporated llc ltd limited corp corporation co company gmbh ag sa sas plc pvt private pty bv nv srl spa "
    "oy ab as kk llp lp".split()
)


def account_key(company: str) -> str:
    """The memory key of a customer company: 'Acme Corp.' and 'ACME, Inc' are the same account."""
    ascii_name = unicodedata.normalize("NFKD", company).encode("ascii", "ignore").decode().lower()
    words = re.findall(r"[a-z0-9]+", ascii_name)
    while len(words) > 1 and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    # Names without latin letters or digits keep their own characters (a key must fit in a URL path segment).
    key = "-".join(words) or re.sub(r"[\s/\\]+", "-", company.strip().lower()).strip("-")
    if not key:
        raise ValueError("the company name is empty")
    return key[:120]


def _record(row: MemoryEntry) -> MemoryRecord:
    return MemoryRecord(
        scope=MemoryScope(row.scope),
        key=row.scope_key,
        version=row.version,
        content=dict(row.content or {}),
        updated_at=row.updated_at,
        written_by=row.written_by,
    )
