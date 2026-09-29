"""SSRF protection for replay.

Every test is offline: DNS is faked and HTTP is mocked. Covers the required
vectors: localhost, loopback, private ranges, link-local/metadata, blocked
schemes, redirects into private space, and DNS that resolves to private IPs.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from app.main import create_app

from tests.conftest import ADMIN_TOKEN, create_tables, drop_tables, make_settings

PUBLIC_IP = "93.184.216.34"


@pytest_asyncio.fixture
async def ssrf_env() -> AsyncIterator:
    applications: list = []
    clients: list = []

    async def _make(handler=None, resolved: dict[str, list[str]] | None = None, **overrides):
        application = create_app(make_settings(**overrides))
        await create_tables(application)

        def client_factory(backend=None) -> httpx.AsyncClient:
            return httpx.AsyncClient(
                transport=httpx.MockTransport(handler or _deny_all), follow_redirects=False
            )

        async def fake_resolver(hostname: str) -> list[str]:
            if resolved and hostname in resolved:
                return resolved[hostname]
            if resolved is not None:
                raise OSError(f"no dns mapping configured for {hostname}")
            return [PUBLIC_IP]

        application.state.replay_service.client_factory = client_factory
        application.state.replay_service.resolver = fake_resolver

        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://testserver"
        )
        client.headers["Authorization"] = f"Bearer {ADMIN_TOKEN}"
        applications.append(application)
        clients.append(client)
        return application, client

    yield _make
    for c in clients:
        await c.aclose()
    for a in applications:
        await drop_tables(a)
        await a.state.engine.dispose()


def _deny_all(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no HTTP call should happen for blocked targets: {request.url}")


async def _replay(client, target: str) -> dict:
    ep = (await client.post("/api/endpoints", json={"name": "ssrf"})).json()["data"]
    await client.post(ep["webhook_url"], json={"ping": True})
    lst = (await client.get(f"/api/endpoints/{ep['id']}/requests")).json()["data"]
    request_id = lst["items"][0]["id"]
    resp = await client.post(f"/api/requests/{request_id}/replay", json={"target_url": target})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


BLOCKED_TARGETS = [
    "https://localhost/x",
    "https://127.0.0.1/x",
    "https://127.8.8.8/x",
    "https://10.0.0.1/x",
    "https://172.16.0.5/x",
    "https://172.31.255.255/x",
    "https://192.168.1.100/x",
    "https://169.254.169.254/latest/meta-data/",
    "https://[::1]/x",
    "https://[fe80::1]/x",
    "https://[fc00::1]/x",
    "https://0.0.0.0/x",
    "https://100.64.0.1/x",
    "https://metadata.google.internal/computeMetadata/v1/",
    "https://service.internal/x",
    "https://box.local/x",
    "https://nas.home.arpa/x",
    "ftp://example.com/file",
    "gopher://example.com/",
    "file:///etc/passwd",
    "javascript:alert(1)",
]


class TestBlockedTargets:
    @pytest.mark.parametrize("target", BLOCKED_TARGETS)
    async def test_blocked_targets_never_reach_network(self, ssrf_env, target):
        _app, client = await ssrf_env()
        record = await _replay(client, target)
        assert record["status"] == "blocked", f"{target}: {record}"
        assert record["error_message"].startswith("Blocked by SSRF protection")

    async def test_http_blocked_by_default(self, ssrf_env):
        _app, client = await ssrf_env()  # allow_http_replay defaults to False
        record = await _replay(client, "http://public.example.com/x")
        assert record["status"] == "blocked"
        assert "https" in record["error_message"]

    async def test_missing_hostname_blocked(self, ssrf_env):
        _app, client = await ssrf_env()
        record = await _replay(client, "https://")
        assert record["status"] == "blocked"

    async def test_credentials_in_url_blocked(self, ssrf_env):
        _app, client = await ssrf_env()
        record = await _replay(client, "https://user:pass@example.com/x")
        assert record["status"] == "blocked"

    async def test_dns_failure_blocked(self, ssrf_env):
        _app, client = await ssrf_env(resolved={})  # resolver raises OSError
        record = await _replay(client, "https://nx.example.com/x")
        assert record["status"] == "blocked"
        assert "DNS" in record["error_message"]


class TestDnsBasedBypasses:
    async def test_public_name_resolving_to_private_ip(self, ssrf_env):
        _app, client = await ssrf_env(resolved={"rebind.example.com": ["10.9.9.9"]})
        record = await _replay(client, "https://rebind.example.com/x")
        assert record["status"] == "blocked"
        assert "10.9.9.9" in record["error_message"]

    async def test_public_name_resolving_to_metadata_ip(self, ssrf_env):
        _app, client = await ssrf_env(resolved={"evil.example.com": ["169.254.169.254"]})
        record = await _replay(client, "https://evil.example.com/latest/meta-data/")
        assert record["status"] == "blocked"

    async def test_all_addresses_must_pass(self, ssrf_env):
        # One public + one private address -> still blocked (fail closed).
        _app, client = await ssrf_env(resolved={"mixed.example.com": [PUBLIC_IP, "192.168.0.10"]})
        record = await _replay(client, "https://mixed.example.com/x")
        assert record["status"] == "blocked"


class TestRedirectBypasses:
    async def test_redirect_to_private_ip_blocked(self, ssrf_env):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(302, headers={"Location": "https://169.254.169.254/latest"})

        _app, client = await ssrf_env(handler)
        record = await _replay(client, "https://redirector.example.com/start")
        assert record["status"] == "blocked"
        # Only the first (public) hop ever hit the network.
        assert calls == ["https://redirector.example.com/start"]

    async def test_https_to_http_downgrade_blocked_by_default(self, ssrf_env):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "http://public.example.com/plain"})

        _app, client = await ssrf_env(handler)  # allow_http_replay=False
        record = await _replay(client, "https://redirector.example.com/start")
        assert record["status"] == "blocked"

    async def test_redirect_to_localhost_blocked(self, ssrf_env):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(301, headers={"Location": "https://localhost:9000/admin"})

        _app, client = await ssrf_env(handler, allow_http_replay=True)
        record = await _replay(client, "https://redirector.example.com/start")
        assert record["status"] == "blocked"


class TestExplicitOptIns:
    async def test_allow_http_permits_public_http(self, ssrf_env):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="ok")

        _app, client = await ssrf_env(handler, allow_http_replay=True)
        record = await _replay(client, "http://public.example.com/x")
        assert record["status"] == "success"

    async def test_allow_private_permits_loopback_for_local_demo(self, ssrf_env):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"mock": True})

        _app, client = await ssrf_env(
            handler, allow_http_replay=True, replay_allow_private_networks=True
        )
        record = await _replay(client, "http://127.0.0.1:8000/mock/receiver")
        assert record["status"] == "success"
        assert record["response_status"] == 200


class TestUnitChecks:
    async def test_validate_target_unit(self):
        from app.services.ssrf import UnsafeTargetError, validate_target

        async def resolver(hostname: str) -> list[str]:
            return [PUBLIC_IP]

        await validate_target(
            "https://ok.example.com", allow_http=False, allow_private=False, resolver=resolver
        )
        with pytest.raises(UnsafeTargetError):
            await validate_target(
                "http://ok.example.com", allow_http=False, allow_private=False, resolver=resolver
            )
