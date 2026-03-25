import asyncio
import time


class TokenBucketRateLimiter:
    """Async token bucket rate limiter."""

    def __init__(self, rate: float = 1.0, capacity: float = 5.0):
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                self._last_refill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait_time = (1.0 - self._tokens) / self._rate
            await asyncio.sleep(wait_time)
