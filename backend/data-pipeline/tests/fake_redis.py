"""A small in-process stand-in for the Redis commands the staging queue uses.

The queue's whole point is that work outlives the process, so its Redis code path
is the one that must be tested - not the memory fallback. Injecting this client
exercises that path without needing a broker, and lets a test simulate a restart
by building a fresh queue over the same store.
"""
from __future__ import annotations

import fnmatch
import time
from typing import Any, Optional


class FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.strings: dict[str, tuple[str, Optional[float]]] = {}  # value, expires_at

    # ---- lists -----------------------------------------------------------
    def lpush(self, key: str, *values: str) -> int:
        bucket = self.lists.setdefault(key, [])
        for value in values:
            bucket.insert(0, value)
        return len(bucket)

    def rpush(self, key: str, *values: str) -> int:
        bucket = self.lists.setdefault(key, [])
        bucket.extend(values)
        return len(bucket)

    def rpop(self, key: str) -> Optional[str]:
        bucket = self.lists.get(key) or []
        return bucket.pop() if bucket else None

    def rpoplpush(self, src: str, dst: str) -> Optional[str]:
        value = self.rpop(src)
        if value is not None:
            self.lpush(dst, value)
        return value

    def brpoplpush(self, src: str, dst: str, timeout: int = 0) -> Optional[str]:
        return self.rpoplpush(src, dst)

    def lrem(self, key: str, count: int, value: str) -> int:
        bucket = self.lists.get(key) or []
        removed = 0
        limit = count if count > 0 else len(bucket)
        while value in bucket and removed < limit:
            bucket.remove(value)
            removed += 1
        return removed

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        bucket = self.lists.get(key) or []
        return bucket[start : (end + 1 if end >= 0 else len(bucket))]

    def llen(self, key: str) -> int:
        return len(self.lists.get(key) or [])

    # ---- sorted sets -----------------------------------------------------
    def zadd(self, key: str, mapping: dict[str, float]) -> int:
        bucket = self.zsets.setdefault(key, {})
        added = sum(1 for m in mapping if m not in bucket)
        bucket.update(mapping)
        return added

    def zrem(self, key: str, *members: str) -> int:
        bucket = self.zsets.get(key) or {}
        return sum(1 for m in members if bucket.pop(m, None) is not None)

    def zrangebyscore(self, key: str, low: float, high: float, start: int = 0, num: Optional[int] = None) -> list[str]:
        bucket = self.zsets.get(key) or {}
        ordered = [m for m, score in sorted(bucket.items(), key=lambda kv: kv[1]) if low <= score <= high]
        sliced = ordered[start:]
        return sliced[:num] if num is not None else sliced

    def zcard(self, key: str) -> int:
        return len(self.zsets.get(key) or {})

    # ---- strings / keys --------------------------------------------------
    def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        self.strings[key] = (value, time.time() + ex if ex else None)
        return True

    def exists(self, key: str) -> int:
        entry = self.strings.get(key)
        if entry is None:
            return 0
        _, expires_at = entry
        if expires_at is not None and expires_at < time.time():
            self.strings.pop(key, None)
            return 0
        return 1

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            removed += bool(self.lists.pop(key, None) or self.zsets.pop(key, None) or self.strings.pop(key, None))
        return removed

    def scan_iter(self, match: str = "*", count: int = 100):
        for key in list(self.lists.keys()):
            if fnmatch.fnmatch(key, match):
                yield key

    def ping(self) -> bool:
        return True

    # ---- pipeline --------------------------------------------------------
    def pipeline(self) -> "FakePipeline":
        return FakePipeline(self)

    def expire_heartbeat(self, key: str) -> None:
        """Test helper: make a consumer look dead."""
        self.strings.pop(key, None)


class FakePipeline:
    def __init__(self, client: FakeRedis) -> None:
        self._client = client
        self._ops: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str):
        def queue_op(*args: Any, **kwargs: Any) -> "FakePipeline":
            self._ops.append((name, args, kwargs))
            return self

        return queue_op

    def execute(self) -> list[Any]:
        results = [getattr(self._client, name)(*args, **kwargs) for name, args, kwargs in self._ops]
        self._ops.clear()
        return results
