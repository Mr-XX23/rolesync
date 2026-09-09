import asyncio
import random
import time
from typing import Any, Callable, Coroutine

class AsyncTokenBucketRateLimiter:
    """
    Asynchronous token-bucket rate limiter.
    Ensures outbound requests to external APIs (Notion, Slack, Google) stay strictly
    within provider quotas, preventing HTTP 429 (Too Many Requests).
    """

    DEFAULT_LIMITS: dict[str, tuple[float, float]] = {
        # provider -> (rate_per_sec, max_burst)
        "notion": (3.0, 3.0),         # Notion hard limit: 3 req/sec per workspace
        "slack": (1.5, 4.0),          # Slack Tier 2/3 limits
        "gmail": (10.0, 15.0),        # Google user rate limits
        "gdrive": (10.0, 15.0),
        "calendar": (10.0, 15.0),
        "googlecalendar": (10.0, 15.0),
        "googledrive": (10.0, 15.0),
    }

    def __init__(self) -> None:
        self._tokens: dict[str, float] = {}
        self._last_refill: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, provider: str) -> asyncio.Lock:
        if provider not in self._locks:
            self._locks[provider] = asyncio.Lock()
        return self._locks[provider]

    async def acquire(self, provider: str, cost: float = 1.0) -> None:
        """Blocks until sufficient tokens are available for the provider."""
        prov = provider.lower()
        rate, burst = self.DEFAULT_LIMITS.get(prov, (5.0, 10.0))
        lock = self._get_lock(prov)

        async with lock:
            now = time.monotonic()
            if prov not in self._last_refill:
                self._tokens[prov] = burst
                self._last_refill[prov] = now

            # Refill tokens based on elapsed time
            elapsed = now - self._last_refill[prov]
            self._tokens[prov] = min(burst, self._tokens[prov] + elapsed * rate)
            self._last_refill[prov] = now

            if self._tokens[prov] < cost:
                wait_time = (cost - self._tokens[prov]) / rate
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    # Update refill after sleep
                    now = time.monotonic()
                    elapsed = now - self._last_refill[prov]
                    self._tokens[prov] = min(burst, self._tokens[prov] + elapsed * rate)
                    self._last_refill[prov] = now

            self._tokens[prov] -= cost


# Global singleton rate limiter
global_rate_limiter = AsyncTokenBucketRateLimiter()


async def execute_with_backoff(
    provider: str,
    action: Callable[[], Coroutine[Any, Any, Any] | Any],
    max_retries: int = 3,
    base_backoff: float = 1.0,
) -> Any:
    """
    Executes a callable with rate-limiting and jittered exponential backoff
    specifically catching rate limit (429) or transient (500, 502, 503, 504) failures.
    """
    for attempt in range(max_retries + 1):
        await global_rate_limiter.acquire(provider)
        try:
            res = action()
            if asyncio.iscoroutine(res):
                return await res
            return res
        except Exception as err:
            err_str = str(err).lower()
            is_rate_limit = "429" in err_str or "rate" in err_str or "quota" in err_str
            is_transient = any(code in err_str for code in ("500", "502", "503", "504", "timeout", "econnreset"))

            if (is_rate_limit or is_transient) and attempt < max_retries:
                # Calculate backoff with jitter
                delay = (base_backoff * (2 ** attempt)) + (random.uniform(0.1, 0.5))
                if is_rate_limit:
                    delay = max(delay, 2.0 * (attempt + 1))
                print(f"[RateLimiter:{provider}] Encountered {err}. Retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})...")
                await asyncio.sleep(delay)
            else:
                raise err
