"""Webhook ingestion: capture fidelity, response behavior, limits, auth."""

from datetime import timedelta

import pytest
from app.models import WebhookEndpoint
from app.util import utcnow
from sqlalchemy import update


async def expire_endpoint(app, endpoint_id: int, hours_ago: float = 1.0) -> None:
    async with app.state.session_factory() as session:
        await session.execute(
            update(WebhookEndpoint)
            .where(WebhookEndpoint.id == endpoint_id)
            .values(expires_at=utcnow() - timedelta(hours=hours_ago))
        )
        await session.commit()


async def get_request_detail(client, endpoint_id: int) -> dict:
    lst = await client.get(f"/api/endpoints/{endpoint_id}/requests")
    items = lst.json()["data"]["items"]
    assert items, "expected at least one recorded request"
    resp = await client.get(f"/api/requests/{items[0]['id']}")
    return resp.json()["data"]


class TestCapture:
    async def test_post_json_full_capture(self, client, make_endpoint):
        ep = await make_endpoint(name="orders")
        resp = await client.post(
            ep["webhook_url"],
            json={"event": "order.created", "order_id": 12345, "amount": 199.99},
            params={"source": "stripe", "attempt": "1"},
            headers={"X-Event-Type": "order.created"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.json() == {"received": True}

        detail = await get_request_detail(client, ep["id"])
        assert detail["method"] == "POST"
        assert detail["path"] == f"/hook/{ep['public_id']}"
        assert detail["query_parameters"] == {"source": "stripe", "attempt": "1"}
        assert detail["body_json"] == {
            "event": "order.created",
            "order_id": 12345,
            "amount": 199.99,
        }
        assert detail["content_type"] == "application/json"
        assert detail["body_size"] > 0
        assert detail["headers"]["x-event-type"] == "order.created"
        assert detail["signature_status"] == "not_configured"
        assert detail["ingest_auth_status"] == "not_configured"
        assert detail["response_status"] == 200
        assert detail["processing_duration_ms"] >= 0
        assert detail["replayable"] is True

    async def test_raw_body_preserved_for_invalid_json(self, client, make_endpoint):
        ep = await make_endpoint()
        resp = await client.post(
            ep["webhook_url"],
            content=b'{"broken json',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        detail = await get_request_detail(client, ep["id"])
        assert detail["body_json"] is None  # parse failed...
        assert detail["body_text"] == '{"broken json'  # ...but raw text survived
        assert detail["body_size"] == len('{"broken json')

    async def test_binary_body_preserved(self, client, make_endpoint):
        ep = await make_endpoint()
        payload = b"\x00\x01\x02\xff-binary"
        resp = await client.post(ep["webhook_url"], content=payload)
        assert resp.status_code == 200
        detail = await get_request_detail(client, ep["id"])
        assert detail["body_size"] == len(payload)
        assert detail["body_json"] is None

    async def test_get_without_content_type(self, client, make_endpoint):
        ep = await make_endpoint()
        resp = await client.get(ep["webhook_url"], params={"q": "health-check"})
        assert resp.status_code == 200
        detail = await get_request_detail(client, ep["id"])
        assert detail["method"] == "GET"
        assert detail["query_parameters"] == {"q": "health-check"}
        assert detail["body_json"] is None

    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def test_common_methods_accepted(self, client, make_endpoint, method):
        ep = await make_endpoint()
        resp = await client.request(method, ep["webhook_url"], content=b"x")
        assert resp.status_code == 200

    async def test_head_returns_no_body(self, client, make_endpoint):
        ep = await make_endpoint()
        resp = await client.head(ep["webhook_url"])
        assert resp.status_code == 200
        assert resp.content == b""

    async def test_json_without_content_type_header(self, client, make_endpoint):
        ep = await make_endpoint()
        resp = await client.post(
            ep["webhook_url"], content=b'{"smuggled": true}'
        )
        assert resp.status_code == 200
        detail = await get_request_detail(client, ep["id"])
        assert detail["body_json"] == {"smuggled": True}


class TestResponseConfiguration:
    async def test_custom_status_body_content_type(self, client, make_endpoint):
        ep = await make_endpoint(
            response_status=202,
            response_body='{"queued": "maybe"}',
            response_content_type="application/custom+json",
        )
        resp = await client.post(ep["webhook_url"], json={"a": 1})
        assert resp.status_code == 202
        assert resp.headers["content-type"].startswith("application/custom+json")
        assert resp.json() == {"queued": "maybe"}

    async def test_server_error_response_code(self, client, make_endpoint):
        ep = await make_endpoint(response_status=500, response_body="boom")
        resp = await client.post(ep["webhook_url"])
        assert resp.status_code == 500
        assert resp.text == "boom"

    async def test_response_delay_applied(self, client, make_endpoint):
        import time

        ep = await make_endpoint(response_delay_ms=250)
        start = time.monotonic()
        resp = await client.post(ep["webhook_url"])
        elapsed = time.monotonic() - start
        assert resp.status_code == 200
        assert elapsed >= 0.2


class TestRejections:
    async def test_unknown_public_id_404(self, client):
        resp = await client.post("http://testserver/hook/does-not-exist")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "endpoint_not_found"

    async def test_expired_endpoint_410_and_recorded(self, client, make_endpoint, app):
        ep = await make_endpoint()
        await expire_endpoint(app, ep["id"])
        resp = await client.post(ep["webhook_url"], json={"late": True})
        assert resp.status_code == 410
        assert resp.json()["error"]["code"] == "endpoint_expired"
        lst = await client.get(f"/api/endpoints/{ep['id']}/requests")
        assert lst.json()["data"]["total"] == 1  # rejected attempt is recorded

    async def test_disabled_endpoint_409(self, client, make_endpoint):
        ep = await make_endpoint()
        resp = await client.patch(f"/api/endpoints/{ep['id']}", json={"enabled": False})
        assert resp.status_code == 200
        resp = await client.post(ep["webhook_url"], json={"a": 1})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "endpoint_disabled"


class TestIngestToken:
    async def test_missing_token_401_and_recorded(self, client, make_endpoint):
        ep = await make_endpoint(ingest_token="s3cret-token")
        resp = await client.post(ep["webhook_url"], json={"a": 1})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "invalid_ingest_token"
        detail = await get_request_detail(client, ep["id"])
        assert detail["ingest_auth_status"] == "invalid"
        assert detail["body_text"] is not None  # body still captured for debugging

    async def test_wrong_token_401(self, client, make_endpoint):
        ep = await make_endpoint(ingest_token="s3cret-token")
        resp = await client.post(
            ep["webhook_url"], json={"a": 1}, headers={"X-Webhook-Token": "nope"}
        )
        assert resp.status_code == 401

    async def test_correct_token_accepted(self, client, make_endpoint):
        ep = await make_endpoint(ingest_token="s3cret-token")
        resp = await client.post(
            ep["webhook_url"], json={"a": 1}, headers={"X-Webhook-Token": "s3cret-token"}
        )
        assert resp.status_code == 200
        detail = await get_request_detail(client, ep["id"])
        assert detail["ingest_auth_status"] == "valid"

    async def test_token_value_not_stored_in_plaintext(self, client, make_endpoint, db_session):
        from app.models import WebhookEndpoint
        from sqlalchemy import select

        ep = await make_endpoint(ingest_token="s3cret-token")
        stored = await db_session.scalar(
            select(WebhookEndpoint.ingest_token_hash).where(WebhookEndpoint.id == ep["id"])
        )
        assert stored is not None
        assert stored != "s3cret-token"
        assert len(stored) == 64  # sha256 hex


class TestBodySizeLimit:
    @pytest.fixture
    async def small_client(self):
        from app.main import create_app
        from tests.conftest import create_tables, drop_tables, make_settings

        application = create_app(make_settings(max_body_size=100))
        await create_tables(application)
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            ac.headers["Authorization"] = "Bearer test-admin-token"
            yield ac, application
        await drop_tables(application)
        await application.state.engine.dispose()

    async def test_oversized_body_413_and_stub_recorded(self, small_client, make_endpoint):
        client, _app = small_client
        resp = await client.post("/api/endpoints", json={"name": "cap"})
        ep = resp.json()["data"]
        big = b"x" * 500
        resp = await client.post(ep["webhook_url"], content=big)
        assert resp.status_code == 413
        assert resp.json()["error"]["code"] == "payload_too_large"
        detail = await get_request_detail(client, ep["id"])
        assert detail["body_size"] == 500
        assert detail["body_text"] is None  # oversized body is NOT retained

    async def test_content_length_precheck(self, small_client):
        client, _app = small_client
        resp = await client.post("/api/endpoints", json={"name": "cap2"})
        ep = resp.json()["data"]
        resp = await client.post(
            ep["webhook_url"],
            content=b"x" * 150,
            headers={"Content-Length": "100000"},
        )
        assert resp.status_code == 413


class TestHistoryCap:
    async def test_max_requests_rolling_window(self, client, make_endpoint):
        ep = await make_endpoint(max_requests=2)
        for i in range(4):
            resp = await client.post(ep["webhook_url"], json={"i": i})
            assert resp.status_code == 200
        detail = await client.get(f"/api/endpoints/{ep['id']}")
        assert detail.json()["data"]["request_count"] == 4  # lifetime counter
        lst = await client.get(f"/api/endpoints/{ep['id']}/requests?page_size=50")
        data = lst.json()["data"]
        assert data["total"] == 2  # only newest retained
        bodies = []
        for item in data["items"]:
            d = await client.get(f"/api/requests/{item['id']}")
            bodies.append(d.json()["data"]["body_json"]["i"])
        assert sorted(bodies) == [2, 3]  # oldest two were pruned
