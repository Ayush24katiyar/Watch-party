"""Token-bucket rate limiter (S-7).

Pure Python with an injectable clock so it can be unit-tested without sleeping.
"""

import time
from collections.abc import Callable


class TokenBucket:
    def __init__(
        self,
        rate_per_second: float,
        capacity: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        self._rate = float(rate_per_second)
        # Default burst = one second of traffic.
        self._capacity = float(capacity) if capacity is not None else max(1.0, self._rate)
        self._tokens = self._capacity
        self._clock = clock
        self._last_refill = clock()

    def consume(self, tokens: float = 1.0) -> bool:
        self._refill()
        if self._tokens < tokens:
            return False
        self._tokens -= tokens
        return True

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last_refill)
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now
