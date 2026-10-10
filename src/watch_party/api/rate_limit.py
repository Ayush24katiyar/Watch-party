"""In-memory per-IP rate limiter for REST endpoints (S-8, S-9).

Single-process dev-scale implementation: one TokenBucket per (scope, IP).
Memory is bounded by pruning all buckets when the map grows large; stricter
storage is part of the Phase 8 hardening review.
"""

from threading import Lock

from watch_party.domain.rate_limit import TokenBucket

_MAX_BUCKETS = 10_000


class IpRateLimiter:
    def __init__(self, per_minute: float) -> None:
        self._per_minute = per_minute
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = Lock()

    def allow(self, ip: str) -> bool:
        with self._lock:
            bucket = self._buckets.get(ip)
            if bucket is None:
                if len(self._buckets) >= _MAX_BUCKETS:
                    self._buckets.clear()
                bucket = TokenBucket(
                    rate_per_second=self._per_minute / 60.0,
                    # Burst up to a full minute's worth of requests, refilling at per_minute/60.
                    capacity=self._per_minute,
                )
                self._buckets[ip] = bucket
            return bucket.consume()

    def reset(self) -> None:
        """Test hook: drop all per-IP state so tests start from a clean budget."""
        with self._lock:
            self._buckets.clear()
