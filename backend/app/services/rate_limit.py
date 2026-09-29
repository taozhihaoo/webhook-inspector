"""Lightweight in-process sliding-window rate limiter.

This is a single-instance limiter: counters live in the memory of one API
process. Multi-node deployments would need a shared store (documented as
future work; deliberately out of scope for v1).
"""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass


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

    def check(self, key: str) -> RateLimitResult:
        now = self.clock()
        window_start = now - self.window_seconds
        hits = self._hits.setdefault(key, deque())

        while hits and hits[0] <= window_start:
            hits.popleft()

        if len(hits) >= self.limit:
            retry_after = max(1, int(hits[0] + self.window_seconds - now) + 1)
            return RateLimitResult(
                allowed=False,
                limit=self.limit,
                remaining=0,
                retry_after_seconds=retry_after,
                reset_epoch=int(now + retry_after),
            )

        hits.append(now)
        return RateLimitResult(
            allowed=True,
            limit=self.limit,
            remaining=self.limit - len(hits),
            retry_after_seconds=0,
            reset_epoch=int(now + self.window_seconds),
        )
