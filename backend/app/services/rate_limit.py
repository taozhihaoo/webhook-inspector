"""Lightweight in-process sliding-window rate limiter.

This is a single-instance limiter: counters live in the memory of one API
process. Multi-node deployments would need a shared store (documented as
future work; deliberately out of scope for v1).

State growth is bounded: fully expired keys are dropped on access, and a
sweep caps the number of tracked keys even when clients rotate source IPs.
"""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

MAX_TRACKED_KEYS = 10_000


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int
    reset_epoch: int


class SlidingWindowRateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}

    def _purge_expired(self, key: str, window_start: float) -> deque[float] | None:
        hits = self._hits.get(key)
        if hits is None:
            return None
        while hits and hits[0] <= window_start:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return None
        return hits

    def _sweep(self, window_start: float) -> None:
        for key in list(self._hits):
            self._purge_expired(key, window_start)

    def check(self, key: str) -> RateLimitResult:
        now = self.clock()
        window_start = now - self.window_seconds

        if len(self._hits) > MAX_TRACKED_KEYS:
            self._sweep(window_start)
            # Under adversarial key rotation (unique IPs within one window)
            # expired-key sweeping is not enough: hard-evict the oldest
            # entries to keep memory bounded. Evicted counters simply start
            # fresh on their next hit.
            while len(self._hits) >= MAX_TRACKED_KEYS:
                oldest = next(iter(self._hits))
                del self._hits[oldest]

        hits = self._purge_expired(key, window_start)

        if hits is not None and len(hits) >= self.limit:
            retry_after = max(1, int(hits[0] + self.window_seconds - now) + 1)
            return RateLimitResult(
                allowed=False,
                limit=self.limit,
                remaining=0,
                retry_after_seconds=retry_after,
                reset_epoch=int(now + retry_after),
            )

        if hits is None:
            hits = self._hits.setdefault(key, deque())
        hits.append(now)
        return RateLimitResult(
            allowed=True,
            limit=self.limit,
            remaining=self.limit - len(hits),
            retry_after_seconds=0,
            reset_epoch=int(now + self.window_seconds),
        )
