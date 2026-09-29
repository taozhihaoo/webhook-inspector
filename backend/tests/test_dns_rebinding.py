"""DNS rebinding hardening: connections are pinned to validated IPs.

These tests are fully offline. The pinning backend is exercised with a
recording stub (proving *which* address connect_tcp targets), and the
replay flow is exercised with stateful fake resolvers against the mock
HTTP transport.
"""

from collections.abc import AsyncIterator

import httpcore
import httpx
import pytest
import pytest_asyncio
from app.main import create_app
from app.services.replay_service import _PinnedHTTPTransport, _PinningBackend
from tests.conftest import ADMIN_TOKEN, create_tables, drop_tables, make_settings

PUBLIC_IP = "93.184.216.34"


@pytest_asyncio.fixture
async def rebind_env() -> AsyncIterator:
    applications: list = []
    clients: list = []

    async def _make(handler, resolver):
        application = create_app(make_settings())
        await create_tables(application)

        def client_factory(backend=None) -> httpx.AsyncClient:
            return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)

        application.state.replay_service.client_factory = client_factory
        application.state.replay_service.resolver = resolver

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


async def _replay(client, target: str) -> dict:
    ep = (await client.post("/api/endpoints", json={"name": "rebind"})).json()["data"]
    await client.post(ep["webhook_url"], json={"ping": True})
    lst = (await client.get(f"/api/endpoints/{ep['id']}/requests")).json()["data"]
    request_id = lst["items"][0]["id"]
    resp = await client.post(f"/api/requests/{request_id}/replay", json={"target_url": target})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


class _FakeStream:
    """Duck-typed httpcore network stream for offline backend tests."""

    async def write(self, data: bytes, timeout=None) -> None:  # pragma: no cover
        raise AssertionError("no writes expected in offline tests")

    async def aclose(self) -> None: ...

    def get_extra_info(self, key):  # pragma: no cover
        return None


class RecordingBackend(httpcore.AsyncNetworkBackend):
    def __init__(self):
        self.connected: list[tuple[str, int]] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connected.append((str(host), int(port)))
        return _FakeStream()


class TestPinningBackendUnit:
    async def test_connects_to_pinned_ip_not_hostname(self):
        inner = RecordingBackend()
        backend = _PinningBackend(inner=inner)
        backend.pin("target.example.com", 443, PUBLIC_IP)

        await backend.connect_tcp("target.example.com", 443)
        await backend.connect_tcp("unpinned.example.com", 443)

        # Pinned host connects to the validated address; unknown hosts pass
        # through unchanged.
        assert inner.connected == [
            (PUBLIC_IP, 443),
            ("unpinned.example.com", 443),
        ]

    async def test_trailing_dot_and_case_normalised(self):
        inner = RecordingBackend()
        backend = _PinningBackend(inner=inner)
        backend.pin("Target.Example.com.", 443, PUBLIC_IP)
        await backend.connect_tcp("target.example.com", 443)
        assert inner.connected == [(PUBLIC_IP, 443)]

    async def test_ports_are_pinned_separately(self):
        inner = RecordingBackend()
        backend = _PinningBackend(inner=inner)
        backend.pin("host.example.com", 443, PUBLIC_IP)
        # Port 8443 is not pinned -> hostname passes through.
        await backend.connect_tcp("host.example.com", 8443)
        assert inner.connected == [("host.example.com", 8443)]


class TestPinnedTransportPassthrough:
    async def test_url_and_host_header_never_rewritten(self):
        """TLS SNI and Host derive from the URL — the transport must not
        rewrite it to the pinned IP."""
        seen: dict = {}

        class FakeRawStream:
            async def __aiter__(self):
                yield b"ok"

            async def aclose(self):
                return None

        class FakeCoreResponse:
            status = 200
            headers = [(b"content-type", b"text/plain")]
            stream = FakeRawStream()
            extensions = {"http_version": "HTTP/1.1"}

        class FakePool:
            async def handle_async_request(self, request):
                seen["scheme"] = request.url.scheme
                seen["host"] = request.url.host
                seen["target"] = request.url.target
                headers_raw = dict(request.headers)
                seen["host_header"] = (
                    headers_raw.get(b"host") or headers_raw.get(b"Host") or b""
                ).decode()
                return FakeCoreResponse()

        transport = _PinnedHTTPTransport.__new__(_PinnedHTTPTransport)
        transport._pool = FakePool()
        backend = _PinningBackend()
        backend.pin("target.example.com", 443, PUBLIC_IP)

        request = httpx.Request("POST", "https://target.example.com/x", content=b"hi")
        response = await transport.handle_async_request(request)

        # The core request must still address the HOSTNAME (never the pinned
        # IP): scheme/host/target feed TLS SNI and the Host header.
        assert seen["scheme"] == b"https"
        assert seen["host"] == b"target.example.com"
        assert seen["target"] == b"/x"
        assert seen["host_header"] == "target.example.com"
        assert response.status_code == 200
        assert await response.aread() == b"ok"


class TestRebindingScenarios:
    async def test_initially_public_then_private_resolution(self, rebind_env):
        """The classic rebinding attack: DNS returns a public IP for the first
        resolution and a private one later. Validation happens per hop and the
        connection is pinned to the validated address, so a swap between
        validation and connection cannot redirect the request."""
        resolutions: list[str] = []

        async def flip_resolver(hostname: str) -> list[str]:
            resolutions.append(hostname)
            return [PUBLIC_IP] if len(resolutions) <= 1 else ["10.0.0.1"]

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"got": True})

        _app, client = await rebind_env(handler, flip_resolver)

        record = await _replay(client, "https://flip.example.com/hook")
        assert record["status"] == "success"  # pinned to the validated public IP

        # A second replay re-validates: DNS now returns a private address.
        record2 = await _replay(client, "https://flip.example.com/hook")
        assert record2["status"] == "blocked"
        assert "10.0.0.1" in record2["error_message"]

    async def test_redirect_to_rebinding_hostname_blocked(self, rebind_env):
        async def resolver(hostname: str) -> list[str]:
            if hostname.startswith("public."):
                return [PUBLIC_IP]
            return ["192.168.1.1"]

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).endswith("/start"):
                return httpx.Response(302, headers={"Location": "https://rebind.example.com/final"})
            return httpx.Response(200)

        _app, client = await rebind_env(handler, resolver)
        record = await _replay(client, "https://public.example.com/start")
        assert record["status"] == "blocked"
        assert "192.168.1.1" in record["error_message"]


class TestResolvedHostnameVariants:
    @pytest.mark.parametrize(
        ("resolver_ip", "label"),
        [
            ("127.0.0.1", "loopback"),
            ("10.1.2.3", "rfc1918-10"),
            ("192.168.0.20", "rfc1918-192"),
            ("172.20.0.7", "rfc1918-172"),
            ("169.254.169.254", "metadata"),
            ("100.64.0.9", "cgnat"),
            ("::1", "ipv6-loopback"),
            ("fe80::1", "ipv6-link-local"),
            ("0.0.0.0", "unspecified"),
            ("::ffff:127.0.0.1", "ipv4-mapped-ipv6"),
        ],
    )
    async def test_hostname_resolving_to_dangerous_ip_blocked(self, rebind_env, resolver_ip, label):
        async def resolver(hostname: str) -> list[str]:
            return [resolver_ip]

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("must never connect")

        _app, client = await rebind_env(handler, resolver)
        record = await _replay(client, f"https://dangerous-{label}.example.com/x")
        assert record["status"] == "blocked", (label, record)
        assert "Blocked by SSRF protection" in record["error_message"]

    async def test_multiple_addresses_all_must_pass(self, rebind_env):
        async def resolver(hostname: str) -> list[str]:
            return [PUBLIC_IP, "10.9.9.9"]

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("must never connect")

        _app, client = await rebind_env(handler, resolver)
        record = await _replay(client, "https://mixed.example.com/x")
        assert record["status"] == "blocked"


class TestObfuscatedIpForms:
    @pytest.mark.parametrize(
        "url",
        [
            "https://2130706433/x",  # decimal 127.0.0.1
            "https://0x7f000001/x",  # hex 127.0.0.1
            "https://0x7f.0x0.0x0.0x1/x",  # dotted hex
            "https://0177.0.0.1/x",  # dotted octal
            "https://017700000001/x",  # octal stream
        ],
    )
    async def test_obfuscated_ip_hostnames_blocked_without_dns(self, rebind_env, url):
        async def resolver(hostname: str) -> list[str]:  # pragma: no cover
            raise AssertionError("static rules must block before DNS")

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("must never connect")

        _app, client = await rebind_env(handler, resolver)
        record = await _replay(client, url)
        assert record["status"] == "blocked", (url, record)

    async def test_percent_encoded_host_blocked(self, rebind_env):
        async def resolver(hostname: str) -> list[str]:
            raise OSError("resolution failed")

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("must never connect")

        _app, client = await rebind_env(handler, resolver)
        # httpx/urllib parse the percent-encoded netloc; the malformed host
        # cannot resolve, so the DNS-failure path must block it.
        record = await _replay(client, "https://%31%32%37.0.0.1/x")
        assert record["status"] == "blocked"

    async def test_userinfo_trick_blocked(self, rebind_env):
        async def resolver(hostname: str) -> list[str]:
            return [PUBLIC_IP]

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("must never connect")

        _app, client = await rebind_env(handler, resolver)
        record = await _replay(client, "https://safe.example.com@127.0.0.1/x")
        assert record["status"] == "blocked"
        assert "Credentials" in record["error_message"]
