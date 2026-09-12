"""Durable staging queue for ingestion work.

Ingestion used to be handed to an in-process ``asyncio.Queue`` (connector events)
or FastAPI ``BackgroundTasks`` (uploads). Both live only in the serving process's
memory, while the API has *already* answered "queued for parsing". So a restart
silently broke that promise - the document sat at "Parsing" forever with no error
recorded anywhere - and a transient parser or embedding failure lost the document
outright, because the loop printed the error and moved on.

This is the Redis reliable-queue pattern:

    enqueue   LPUSH  pending
    reserve   BLMOVE pending -> inflight:<consumer>   (atomic; survives a crash)
    ack       LREM   inflight:<consumer>
    fail      ZADD   retry (exponential backoff) or LPUSH dead

Nothing leaves ``pending`` without landing in an ``inflight`` list, so a process
that dies mid-job loses nothing: each consumer heartbeats, and work belonging to
a consumer whose heartbeat has expired is reclaimed and retried. Jobs that keep
failing end up in a dead-letter list that can be inspected rather than vanishing.

Redis is optional. Without it the queue degrades to an in-process deque - the old
behaviour, no worse - so local runs and tests need no broker.
"""
from __future__ import annotations

import json
import os
import socket
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover - redis client not installed
    redis_lib = None

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BACKOFF_SECONDS = 10.0
DEFAULT_HEARTBEAT_SECONDS = 60
_TRUTHY = {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


@dataclass
class Job:
    """A unit of ingestion work, durable from the moment it is accepted."""

    kind: str
    payload: dict[str, Any]
    job_id: str = field(default_factory=lambda: f"job_{uuid.uuid4().hex[:16]}")
    attempts: int = 0
    enqueued_at: float = field(default_factory=time.time)
    last_error: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "job_id": self.job_id,
                "kind": self.kind,
                "payload": self.payload,
                "attempts": self.attempts,
                "enqueued_at": self.enqueued_at,
                "last_error": self.last_error,
            },
            default=str,
        )

    @classmethod
    def from_json(cls, raw: str) -> "Job":
        data = json.loads(raw)
        return cls(
            kind=data.get("kind", ""),
            payload=data.get("payload") or {},
            job_id=data.get("job_id") or f"job_{uuid.uuid4().hex[:16]}",
            attempts=int(data.get("attempts") or 0),
            enqueued_at=float(data.get("enqueued_at") or time.time()),
            last_error=data.get("last_error") or "",
        )


class DurableQueue:
    def __init__(
        self,
        name: str = "rag:ingest",
        *,
        max_attempts: Optional[int] = None,
        backoff_seconds: Optional[float] = None,
        heartbeat_seconds: Optional[int] = None,
        consumer_id: str = "",
        client: Any = None,
    ) -> None:
        self.name = name
        self.max_attempts = max_attempts if max_attempts is not None else _env_int("INGEST_QUEUE_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)
        self.backoff_seconds = backoff_seconds if backoff_seconds is not None else _env_float("INGEST_QUEUE_BACKOFF_SECONDS", DEFAULT_BACKOFF_SECONDS)
        self.heartbeat_seconds = heartbeat_seconds if heartbeat_seconds is not None else _env_int("INGEST_QUEUE_HEARTBEAT_SECONDS", DEFAULT_HEARTBEAT_SECONDS)
        # One consumer per process; the hostname keeps it stable across restarts
        # of the same container so its own in-flight work is reclaimed first.
        self.consumer_id = consumer_id or os.environ.get("HOSTNAME", "") or socket.gethostname() or uuid.uuid4().hex[:8]

        self._client = client if client is not None else self._connect()
        # Used only when Redis is unavailable.
        self._memory: deque[Job] = deque()
        self._memory_inflight: dict[str, Job] = {}
        self._memory_dead: list[Job] = []

    # ---- keys ------------------------------------------------------------
    @property
    def pending_key(self) -> str:
        return f"{self.name}:pending"

    @property
    def retry_key(self) -> str:
        return f"{self.name}:retry"

    @property
    def dead_key(self) -> str:
        return f"{self.name}:dead"

    def inflight_key(self, consumer: str = "") -> str:
        return f"{self.name}:inflight:{consumer or self.consumer_id}"

    def heartbeat_key(self, consumer: str = "") -> str:
        return f"{self.name}:hb:{consumer or self.consumer_id}"

    # ---- connection ------------------------------------------------------
    def _connect(self) -> Any:
        if redis_lib is None:
            return None
        if os.environ.get("INGEST_QUEUE_BACKEND", "redis").strip().lower() == "memory":
            return None
        url = os.environ.get("REDIS_URL", "").strip()
        try:
            if url:
                client = redis_lib.Redis.from_url(url, decode_responses=True)
            else:
                client = redis_lib.Redis(
                    host=os.environ.get("REDIS_HOST", "redis"),
                    port=_env_int("REDIS_PORT", 6379),
                    db=_env_int("REDIS_DB", 0),
                    password=os.environ.get("REDIS_PASSWORD", "") or None,
                    decode_responses=True,
                )
            client.ping()
            return client
        except Exception as err:
            print(f"[DurableQueue] Redis unavailable ({err}); staging queue falls back to memory.")
            return None

    def available(self) -> bool:
        """True when work is persisted outside this process."""
        if self._client is None:
            return False
        try:
            self._client.ping()
            return True
        except Exception:
            return False

    # ---- producer --------------------------------------------------------
    def enqueue(self, kind: str, payload: dict[str, Any]) -> Job:
        """Accept a job. Returns once the job is durable (or memory-queued)."""
        job = Job(kind=kind, payload=payload)
        if self._client is not None:
            try:
                self._client.lpush(self.pending_key, job.to_json())
                return job
            except Exception as err:
                print(f"[DurableQueue] Enqueue failed for {job.job_id}: {err}")
        self._memory.append(job)
        return job

    # ---- consumer --------------------------------------------------------
    def reserve(self, timeout: float = 1.0) -> Optional[Job]:
        """Claim the next job, moving it atomically into this consumer's in-flight
        list so a crash cannot drop it."""
        if self._client is not None:
            try:
                self.beat()
                self.promote_due_retries()
                raw = self._client.brpoplpush(self.pending_key, self.inflight_key(), timeout=int(max(1, timeout)))
                return Job.from_json(raw) if raw else None
            except Exception as err:
                print(f"[DurableQueue] Reserve failed: {err}")
                return None

        if not self._memory:
            return None
        job = self._memory.popleft()
        self._memory_inflight[job.job_id] = job
        return job

    def ack(self, job: Job) -> None:
        """Mark a job done and remove it from the in-flight list."""
        if self._client is not None:
            try:
                self._client.lrem(self.inflight_key(), 1, job.to_json())
                return
            except Exception as err:
                print(f"[DurableQueue] Ack failed for {job.job_id}: {err}")
        self._memory_inflight.pop(job.job_id, None)

    def fail(self, job: Job, error: str) -> str:
        """Record a failure: schedule a retry, or dead-letter once attempts run out.

        Returns "retry" or "dead" so the caller can log what happened to the job.
        """
        original = job.to_json()
        job.attempts += 1
        job.last_error = (error or "")[:1000]
        retryable = job.attempts < self.max_attempts
        # Exponential backoff, so a struggling vendor is not hammered.
        ready_at = time.time() + self.backoff_seconds * (2 ** (job.attempts - 1))

        if self._client is not None:
            try:
                pipe = self._client.pipeline()
                pipe.lrem(self.inflight_key(), 1, original)
                if retryable:
                    pipe.zadd(self.retry_key, {job.to_json(): ready_at})
                else:
                    pipe.lpush(self.dead_key, job.to_json())
                pipe.execute()
                return "retry" if retryable else "dead"
            except Exception as err:
                print(f"[DurableQueue] Fail bookkeeping failed for {job.job_id}: {err}")

        self._memory_inflight.pop(job.job_id, None)
        if retryable:
            self._memory.append(job)
            return "retry"
        self._memory_dead.append(job)
        return "dead"

    # ---- maintenance -----------------------------------------------------
    def beat(self) -> None:
        """Refresh this consumer's liveness marker."""
        if self._client is None:
            return
        try:
            self._client.set(self.heartbeat_key(), str(time.time()), ex=self.heartbeat_seconds)
        except Exception:
            pass

    def promote_due_retries(self) -> int:
        """Move retries whose backoff has elapsed back onto the pending list."""
        if self._client is None:
            return 0
        try:
            due = self._client.zrangebyscore(self.retry_key, 0, time.time(), start=0, num=100)
            moved = 0
            for raw in due:
                # Only the mover requeues it, so two workers cannot double-promote.
                if self._client.zrem(self.retry_key, raw):
                    self._client.lpush(self.pending_key, raw)
                    moved += 1
            return moved
        except Exception as err:
            print(f"[DurableQueue] Retry promotion failed: {err}")
            return 0

    def reclaim_stale(self) -> int:
        """Requeue work held by consumers that are no longer alive.

        This is what makes a restart or crash non-destructive: the dead process's
        in-flight jobs go back on the queue instead of being lost.
        """
        if self._client is None:
            return 0
        reclaimed = 0
        try:
            for key in self._client.scan_iter(match=f"{self.name}:inflight:*", count=100):
                consumer = key.rsplit(":", 1)[-1]
                if consumer != self.consumer_id and self._client.exists(self.heartbeat_key(consumer)):
                    continue  # still alive and working
                while True:
                    raw = self._client.rpoplpush(key, self.pending_key)
                    if raw is None:
                        break
                    reclaimed += 1
            if reclaimed:
                print(f"[DurableQueue] Reclaimed {reclaimed} in-flight job(s) from a previous run.")
        except Exception as err:
            print(f"[DurableQueue] Reclaim failed: {err}")
        return reclaimed

    # ---- visibility ------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        if self._client is not None:
            try:
                return {
                    "backend": "redis",
                    "pending": int(self._client.llen(self.pending_key)),
                    "inflight": int(self._client.llen(self.inflight_key())),
                    "retry": int(self._client.zcard(self.retry_key)),
                    "dead": int(self._client.llen(self.dead_key)),
                    "consumer_id": self.consumer_id,
                    "max_attempts": self.max_attempts,
                }
            except Exception as err:
                print(f"[DurableQueue] Stats failed: {err}")
        return {
            "backend": "memory",
            "pending": len(self._memory),
            "inflight": len(self._memory_inflight),
            "retry": 0,
            "dead": len(self._memory_dead),
            "consumer_id": self.consumer_id,
            "max_attempts": self.max_attempts,
            "warning": "Redis unavailable: queued work is lost if this process restarts.",
        }

    @staticmethod
    def _belongs_to(entry: dict[str, Any], tenant_id: str) -> bool:
        return not tenant_id or (entry.get("payload") or {}).get("tenant_id") == tenant_id

    def dead_letters(self, limit: int = 50) -> list[dict[str, Any]]:
        if self._client is not None:
            try:
                raws = self._client.lrange(self.dead_key, 0, max(0, limit - 1))
                return [json.loads(r) for r in raws]
            except Exception as err:
                print(f"[DurableQueue] Dead-letter read failed: {err}")
                return []
        return [json.loads(j.to_json()) for j in self._memory_dead[:limit]]

    def dead_letters_for(self, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return [e for e in self.dead_letters(limit=limit) if self._belongs_to(e, tenant_id)]

    def replay_dead_letters(self, limit: int = 50, tenant_id: str = "") -> int:
        """Put dead-lettered jobs back on the queue with a fresh attempt count.

        `tenant_id` scopes the replay: the queue is service-wide, so a caller must
        not be able to requeue another workspace's jobs.
        """
        replayed = 0
        if self._client is not None:
            try:
                skipped: list[str] = []
                for _ in range(max(0, limit)):
                    raw = self._client.rpop(self.dead_key)
                    if raw is None:
                        break
                    job = Job.from_json(raw)
                    if not self._belongs_to({"payload": job.payload}, tenant_id):
                        skipped.append(raw)
                        continue
                    job.attempts = 0
                    self._client.lpush(self.pending_key, job.to_json())
                    replayed += 1
                for raw in skipped:  # another workspace's jobs stay dead-lettered
                    self._client.rpush(self.dead_key, raw)
                return replayed
            except Exception as err:
                print(f"[DurableQueue] Replay failed: {err}")
                return replayed

        remaining: list[Job] = []
        for job in self._memory_dead:
            if replayed < limit and self._belongs_to({"payload": job.payload}, tenant_id):
                job.attempts = 0
                self._memory.append(job)
                replayed += 1
            else:
                remaining.append(job)
        self._memory_dead = remaining
        return replayed

    def purge(self) -> None:
        """Drop every queue key. Test and operator use only."""
        if self._client is not None:
            try:
                self._client.delete(self.pending_key, self.retry_key, self.dead_key, self.inflight_key())
                return
            except Exception as err:
                print(f"[DurableQueue] Purge failed: {err}")
        self._memory.clear()
        self._memory_inflight.clear()
        self._memory_dead.clear()


ingest_queue = DurableQueue()
