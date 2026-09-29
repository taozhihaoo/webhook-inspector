"""Replay behavior: defaults, edits, records, failures (all via mock transport)."""

from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.main import create_app
from tests.conftest import ADMIN_TOKEN, create_tables, drop_tables, make_settings

PUBLIC_IP = "93.184.216.34"


@pytest_asyncio.fixture
async def replay_env() -> AsyncIterator:
    """App + client wired to a mock HTTP transport and fake DNS."""
    applications: list = []
    clients: list = []

    async def _make(handler, **settings_overrides):
        application = create_app(make_settings(**settings_overrides))
        await create_tables(application)

        def client_factory(backend=None) -> httpx.AsyncClient:
            return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)

        async def fake_resolver(hostname: str) -> list[str]:
            return [PUBLIC_IP]

        application.state.replay_service.client_factory = client_factory
        application.state.replay_service.resolver = fake_resolver

        transport = httpx.ASGITransport(app=application)
        client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
        client.headers["Authorization"] = f"Bearer {ADMIN_TOKEN}"
        applications.append(application)
        clients.append(client)
        return client, application

    yield _make
    for c in clients:
        await c.aclose()
    for a in applications:
        await drop_tables(a)
        await a.state.engine.dispose()


async def setup_captured_request(client) -> tuple[dict, dict]:
    """Create an endpoint + one captured request; return (endpoint, request)."""
    ep = (await client.post("/api/endpoints", json={"name": "replay-src"})).json()["data"]
    resp = await client.post(
        ep["webhook_url"],
        json={"event": "order.created", "order_id": 99},
        headers={"X-Source": "test-suite"},
    )
    assert resp.status_code == 200
    lst = (await client.get(f"/api/endpoints/{ep['id']}/requests")).json()["data"]
    return ep, lst["items"][0]


class TestReplaySuccess:
    async def test_replay_to_endpoint_target(self, replay_env):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"received": True})

        client, app = await replay_env(handler)
        ep, request = await setup_captured_request(client)

        # Configure the endpoint's default target.
        await client.patch(
            f"/api/endpoints/{ep['id']}",
            json={"replay_target_url": "https://target.example.com/hook"},
        )
        resp = await client.post(f"/api/requests/{request['id']}/replay", json={})
        assert resp.status_code == 200, resp.text
        record = resp.json()["data"]
        assert record["status"] == "success"
        assert record["response_status"] == 200
        assert record["target_url"] == "https://target.example.com/hook"
        assert record["duration_ms"] is not None and record["duration_ms"] >= 0
        assert '"received":true' in (record["response_body_preview"] or "").replace(" ", "")

        # The replayed request carried the original method/headers/body.
        assert len(seen) == 1
        sent = seen[0]
        assert sent.method == "POST"
        assert sent.headers["x-source"] == "test-suite"
        assert b'"order_id":99' in sent.content or b"order_id" in sent.content

    async def test_replay_with_edited_body_and_headers(self, replay_env):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(201, text="accepted")

        client, _app = await replay_env(handler)
        _ep, request = await setup_captured_request(client)

        resp = await client.post(
            f"/api/requests/{request['id']}/replay",
            json={
                "target_url": "https://other.example.com/collect",
                "method": "PUT",
                "headers": {"Content-Type": "application/json", "X-Custom": "edited"},
                "body_text": '{"order_id": 100, "edited": true}',
            },
        )
        record = resp.json()["data"]
        assert record["status"] == "success"
        assert record["response_status"] == 201
        sent = seen[0]
        assert sent.method == "PUT"
        assert sent.headers["x-custom"] == "edited"
        assert sent.headers["host"] == "other.example.com"
        assert b'"edited": true' in sent.content

    async def test_duplicate_replays_create_separate_records(self, replay_env):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200)

        client, _app = await replay_env(handler)
        _ep, request = await setup_captured_request(client)
        for _ in range(2):
            await client.post(
                f"/api/requests/{request['id']}/replay",
                json={"target_url": "https://target.example.com/x"},
            )
        history = (await client.get(f"/api/requests/{request['id']}/replays")).json()["data"]
        assert len(history) == 2

    async def test_original_request_unmodified_after_replay(self, replay_env):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200)

        client, _app = await replay_env(handler)
        _ep, request = await setup_captured_request(client)
        before = (await client.get(f"/api/requests/{request['id']}")).json()["data"]

        await client.post(
            f"/api/requests/{request['id']}/replay",
            json={
                "target_url": "https://target.example.com/x",
                "body_text": "changed",
                "method": "DELETE",
            },
        )
        after = (await client.get(f"/api/requests/{request['id']}")).json()["data"]
        assert before["body_text"] == after["body_text"]
        assert before["method"] == after["method"] == "POST"
        assert before["headers"] == after["headers"]

    async def test_redirect_followed_and_validated(self, replay_env):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if str(request.url).endswith("/start"):
                return httpx.Response(302, headers={"Location": "https://target.example.com/final"})
            return httpx.Response(200, text="landed")

        client, _app = await replay_env(handler)
        _ep, request = await setup_captured_request(client)
        resp = await client.post(
            f"/api/requests/{request['id']}/replay",
            json={"target_url": "https://target.example.com/start"},
        )
        record = resp.json()["data"]
        assert record["status"] == "success"
        assert record["response_status"] == 200
        assert calls[-1].endswith("/final")


class TestReplayFailures:
    async def test_connection_error_recorded(self, replay_env):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        client, _app = await replay_env(handler)
        _ep, request = await setup_captured_request(client)
        resp = await client.post(
            f"/api/requests/{request['id']}/replay",
            json={"target_url": "https://unreachable.example.com/x"},
        )
        record = resp.json()["data"]
        assert record["status"] == "error"
        assert "ConnectError" in record["error_message"]
        assert record["response_status"] is None

    async def test_timeout_recorded(self, replay_env):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        client, _app = await replay_env(handler)
        _ep, request = await setup_captured_request(client)
        resp = await client.post(
            f"/api/requests/{request['id']}/replay",
            json={"target_url": "https://slow.example.com/x"},
        )
        record = resp.json()["data"]
        assert record["status"] == "timeout"

    async def test_no_target_configured(self, replay_env):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        client, _app = await replay_env(handler)
        _ep, request = await setup_captured_request(client)
        resp = await client.post(f"/api/requests/{request['id']}/replay", json={})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "no_replay_target"

    async def test_unknown_request_404(self, replay_env):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        client, _app = await replay_env(handler)
        resp = await client.post("/api/requests/99999/replay", json={})
        assert resp.status_code == 404


class TestClone:
    async def test_clone_returns_editable_copy(self, replay_env):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        client, _app = await replay_env(handler)
        ep, request = await setup_captured_request(client)
        await client.patch(
            f"/api/endpoints/{ep['id']}",
            json={"replay_target_url": "https://target.example.com/hook"},
        )
        resp = await client.post(f"/api/requests/{request['id']}/clone")
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["method"] == "POST"
        assert data["target_url"] == "https://target.example.com/hook"
        assert "order_id" in data["body_text"]
        assert data["headers"]["x-source"] == "test-suite"
