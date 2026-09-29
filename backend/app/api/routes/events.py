"""Server-Sent Events stream: live notifications when new requests arrive.

Fetch-based clients (like the frontend) send the admin token as a normal
Authorization header; EventSource cannot, which is why no cookie/query-token
fallback is used.
"""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from starlette.responses import StreamingResponse

from app.api.deps import require_admin
from app.errors import EndpointNotFound
from app.models import WebhookEndpoint
from app.services.events import EventBroker

router = APIRouter(dependencies=[Depends(require_admin)])

KEEPALIVE_SECONDS = 15


async def sse_event_stream(
    request: Request, broker: EventBroker, queue, endpoint_id: int
) -> AsyncIterator[str]:
    """Yield SSE frames until the client disconnects.

    Extracted from the route so tests can consume the generator directly
    (httpx's ASGITransport buffers whole responses, which would deadlock on an
    infinite stream).
    """
    try:
        yield "retry: 3000\n\n"
        yield f"event: connected\ndata: {json.dumps({'endpoint_id': endpoint_id})}\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield f"event: request\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"
    finally:
        broker.unsubscribe(endpoint_id, queue)


@router.get("/endpoints/{endpoint_id}/events")
async def stream_events(endpoint_id: int, request: Request) -> StreamingResponse:
    # Short-lived session: it must be closed *before* streaming starts, so the
    # connection doesn't hold a database slot for the lifetime of the stream.
    async with request.app.state.session_factory() as session:
        if await session.get(WebhookEndpoint, endpoint_id) is None:
            raise EndpointNotFound()

    broker: EventBroker = request.app.state.broker
    queue = broker.subscribe(endpoint_id)
    return StreamingResponse(
        sse_event_stream(request, broker, queue, endpoint_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
