"""SSE live updates: broker unit behavior + end-to-end stream delivery."""

import asyncio
import json

from app.api.routes.events import sse_event_stream
from app.services.events import EventBroker


class TestBrokerUnit:
    def test_publish_reaches_subscriber(self):
        broker = EventBroker()
        queue = broker.subscribe(1)
        broker.publish(1, {"request_id": 7})
        assert queue.get_nowait() == {"request_id": 7}

    def test_isolated_per_endpoint(self):
        broker = EventBroker()
        q1 = broker.subscribe(1)
        broker.subscribe(2)
        broker.publish(2, {"request_id": 8})
        assert q1.empty()

    def test_unsubscribe_stops_delivery(self):
        broker = EventBroker()
        queue = broker.subscribe(1)
        broker.unsubscribe(1, queue)
        broker.publish(1, {"request_id": 9})
        assert queue.empty()
        assert broker.subscriber_count(1) == 0

    def test_slow_consumer_keeps_oldest_and_drops_newest(self):
        broker = EventBroker()
        queue = broker.subscribe(1)
        for i in range(100):  # queue cap is 64
            broker.publish(1, {"i": i})
        assert queue.qsize() == 64
        # A slow consumer keeps the oldest events and silently drops the
        # newest (publish never blocks the ingest path).
        assert queue.get_nowait() == {"i": 0}
        assert list(queue._queue)[-1] == {"i": 63}

    def test_unknown_endpoint_publish_is_noop(self):
        broker = EventBroker()
        broker.publish(999, {})  # must not raise


class _StubRequest:
    """Minimal request stand-in for direct generator consumption."""

    async def is_disconnected(self) -> bool:
        return False


class TestSseStream:
    async def test_stream_yields_retry_connected_and_request_events(self, app, make_endpoint):
        ep = await make_endpoint()
        broker = app.state.broker
        queue = broker.subscribe(ep["id"])
        generator = sse_event_stream(_StubRequest(), broker, queue, ep["id"])

        first = await generator.__anext__()
        assert first == "retry: 3000\n\n"

        connected = await generator.__anext__()
        assert "event: connected" in connected
        assert f'"endpoint_id": {ep["id"]}' in connected

        broker.publish(
            ep["id"],
            {
                "endpoint_id": ep["id"],
                "request_id": 1,
                "method": "POST",
                "received_at": "2026-09-30T00:00:00+00:00",
                "body_size": 2,
                "signature_status": "not_configured",
                "ingest_auth_status": "not_configured",
                "response_status": 200,
            },
        )
        frame = await generator.__anext__()
        assert frame.startswith("event: request\ndata: ")
        payload = json.loads(frame.split("data: ", 1)[1].strip())
        assert payload["endpoint_id"] == ep["id"]
        assert payload["method"] == "POST"

        # Closing the generator unsubscribes from the broker (cleanup path).
        await generator.aclose()
        assert broker.subscriber_count(ep["id"]) == 0

    async def test_stream_requires_auth(self, client, make_endpoint):
        ep = await make_endpoint()
        client.headers.pop("Authorization")
        resp = await client.get(f"/api/endpoints/{ep['id']}/events")
        assert resp.status_code == 401

    async def test_stream_unknown_endpoint_404(self, client):
        resp = await client.get("/api/endpoints/424242/events")
        assert resp.status_code == 404

    async def test_ingest_publishes_event_to_broker(self, client, app, make_endpoint):
        """Full loop: webhook arrives -> subscribers receive the event."""
        ep = await make_endpoint()
        queue = app.state.broker.subscribe(ep["id"])
        resp = await client.post(ep["webhook_url"], json={"live": True})
        assert resp.status_code == 200
        event = await asyncio.wait_for(queue.get(), timeout=2)
        assert event["endpoint_id"] == ep["id"]
        assert event["request_id"] > 0
        assert event["method"] == "POST"
