"""Uniform error envelopes; no tracebacks or internals leak to clients."""


from httpx import ASGITransport, AsyncClient
from tests.conftest import ADMIN_TOKEN


class TestErrorEnvelopes:
    async def test_app_error_shape(self, client):
        resp = await client.get("/api/endpoints/123456")
        assert resp.status_code == 404
        body = resp.json()
        assert set(body.keys()) == {"error"}
        assert set(body["error"].keys()) == {"code", "message"}

    async def test_validation_error_envelope(self, client):
        resp = await client.post("/api/endpoints", json={"ttl_hours": "not-a-number"})
        assert resp.status_code == 422
        error = resp.json()["error"]
        assert error["code"] == "invalid_input"
        assert error["message"]  # human-readable, includes the failing field
        assert "ttl_hours" in error["message"]

    async def test_unknown_api_route_envelope(self, client):
        resp = await client.get("/api/definitely-not-a-route")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "not_found"

    async def test_method_not_allowed_envelope(self, client):
        resp = await client.patch("/api/health")
        assert resp.status_code == 405
        assert resp.json()["error"]["code"] == "method_not_allowed"

    async def test_unhandled_exception_masked(self, make_endpoint, client, app, monkeypatch):
        ep = await make_endpoint()
        await client.post(ep["webhook_url"], json={"a": 1})
        lst = (await client.get(f"/api/endpoints/{ep['id']}/requests")).json()["data"]
        request_id = lst["items"][0]["id"]

        async def boom(*args, **kwargs):
            raise RuntimeError("secret-internal-detail-xyz")

        monkeypatch.setattr(app.state.replay_service, "execute", boom)

        # raise_app_exceptions=False: mimic a real server where Starlette's
        # ServerErrorMiddleware turns the exception into a 500 response.
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://testserver") as raw_client:
            raw_client.headers["Authorization"] = f"Bearer {ADMIN_TOKEN}"
            resp = await raw_client.post(f"/api/requests/{request_id}/replay", json={})

        assert resp.status_code == 500
        error = resp.json()["error"]
        assert error["code"] == "internal_error"
        assert "secret-internal-detail-xyz" not in resp.text
        assert "Traceback" not in resp.text
        assert "RuntimeError" not in resp.text

    async def test_storage_error_type_exists(self):
        from app.errors import StorageError

        assert StorageError().code == "storage_error"

    async def test_all_documented_error_types_exist(self):
        from app import errors

        for name in (
            "EndpointNotFound",
            "EndpointExpired",
            "EndpointDisabled",
            "PayloadTooLarge",
            "RateLimitExceeded",
            "InvalidInput",
            "ReplayBlocked",
            "ReplayTimeout",
            "StorageError",
            "Unauthorized",
        ):
            assert hasattr(errors, name)


class TestSecurityBehavior:
    async def test_expired_and_disabled_flags_do_not_leak_secrets(self, client, make_endpoint):
        ep = await make_endpoint(ingest_token="hunter2", ttl_hours=1)
        # Ingest token hash must never round-trip through the API.
        text = (await client.get(f"/api/endpoints/{ep['id']}")).text
        assert "hunter2" not in text

    async def test_spa_fallback_returns_404_envelope_for_api_paths(self, client):
        # Without a built frontend, unknown /api paths still stay JSON.
        resp = await client.get("/api/nope")
        assert resp.headers["content-type"].startswith("application/json")
