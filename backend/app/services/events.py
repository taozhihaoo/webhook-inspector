"""In-process pub/sub broker used by the SSE stream.

Single-instance by design (same trade-off as the rate limiter): subscribers
only receive events published by the same API process.
"""

import asyncio
from contextlib import suppress

MAX_QUEUE_SIZE = 64


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue[dict]]] = {}

    def subscribe(self, endpoint_id: int) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        self._subscribers.setdefault(endpoint_id, set()).add(queue)
        return queue

    def unsubscribe(self, endpoint_id: int, queue: asyncio.Queue[dict]) -> None:
        queues = self._subscribers.get(endpoint_id)
        if queues is not None:
            queues.discard(queue)
            if not queues:
                self._subscribers.pop(endpoint_id, None)

    def publish(self, endpoint_id: int, event: dict) -> None:
        for queue in list(self._subscribers.get(endpoint_id, ())):
            with suppress(asyncio.QueueFull):  # slow consumer: drop rather than block ingest
                queue.put_nowait(event)

    def subscriber_count(self, endpoint_id: int) -> int:
        return len(self._subscribers.get(endpoint_id, ()))
