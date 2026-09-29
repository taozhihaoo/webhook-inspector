"""Rate limiter: unit behavior + ingest integration (429, headers, per-IP keys)."""

import pytest
from app.services.rate_limit import SlidingWindowRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestSlidingWindowUnit:
    def test_allows_up_to_limit(self):
        clock = FakeClock()
        limiter = SlidingWindowRateLimiter(3, 60, clock=clock)
        for _ in range(3):
            result = limiter.check("key")
            assert result.allowed
        assert result.remaining == 0

    def test_blocks_over_limit_with_retry_after(self):
        clock = FakeClock()
        limiter = SlidingWindowRateLimiter(2, 60, clock=clock)
        limiter.check("key")
        limiter.check("key")
        result = limiter.check("key")
        assert not result.allowed
        assert result.retry_after_seconds >= 1
        assert result.remaining == 0

    def test_window_slides(self):
        clock = FakeClock()
        limiter = SlidingWindowRateLimiter(1, 60, clock=clock)
        assert limiter.check("key").allowed
        assert not limiter.check("key").allowed
        clock.advance(30)
        assert not limiter.check("key").allowed  # still inside window
        clock.advance(31)
        assert limiter.check("key").allowed  # first hit expired

    def test_keys_are_independent(self):
        limiter = SlidingWindowRateLimiter(1, 60, clock=FakeClock())
        assert limiter.check("ip-1").allowed
        assert limiter.check("ip-2").allowed
        assert not limiter.check("ip-1").allowed

    def test_partial_window_expiry(self):
        clock = FakeClock()
        limiter = SlidingWindowRateLimiter(2, 10, clock=clock)
        limiter.check("k")  # t=1000
        clock.advance(6)
        limiter.check("k")  # t=1006
        clock.advance(3)  # t=1009: window start = 999, both hits still inside
        assert not limiter.check("k").allowed
        clock.advance(2)  # t=1011: window start = 1001 -> hit at t=1000 expired
        result = limiter.check("k")
        assert result.allowed
        assert result.remaining == 0  # hit at t=1006 + this one = limit reached


class TestIngestIntegration:
    @pytest.fixture
    async def limited_env(self):
        from app.main import create_app
        from httpx import ASGITransport, AsyncClient
        from tests.conftest import ADMIN_TOKEN, create_tables, drop_tables, make_settings

        application = create_app(
            make_settings(
                rate_limit_requests=3, rate_limit_window_seconds=60, trust_proxy_headers=True
            )
        )
        await create_tables(application)
        client = AsyncClient(transport=ASGITransport(app=application), base_url="http://testserver")
        client.headers["Authorization"] = f"Bearer {ADMIN_TOKEN}"
        yield application, client
        await client.aclose()
        await drop_tables(application)
        await application.state.engine.dispose()

    async def test_429_with_headers_after_limit(self, limited_env):
        _app, client = limited_env
        ep = (await client.post("/api/endpoints", json={"name": "rl"})).json()["data"]
        last = None
        for _ in range(4):
            last = await client.post(
                ep["webhook_url"], content=b"x", headers={"X-Forwarded-For": "9.9.9.9"}
            )
        assert last.status_code == 429
        assert last.json()["error"]["code"] == "rate_limit_exceeded"
        assert int(last.headers["retry-after"]) >= 1
        assert last.headers["x-ratelimit-limit"] == "3"
        assert last.headers["x-ratelimit-remaining"] == "0"

    async def test_success_includes_rate_headers(self, limited_env):
        _app, client = limited_env
        ep = (await client.post("/api/endpoints", json={"name": "rl2"})).json()["data"]
        resp = await client.post(
            ep["webhook_url"], content=b"x", headers={"X-Forwarded-For": "8.8.8.8"}
        )
        assert resp.status_code == 200
        assert resp.headers["x-ratelimit-limit"] == "3"
        assert int(resp.headers["x-ratelimit-remaining"]) == 2

    async def test_per_ip_isolation(self, limited_env):
        _app, client = limited_env
        ep = (await client.post("/api/endpoints", json={"name": "rl3"})).json()["data"]
        for _ in range(3):
            await client.post(
                ep["webhook_url"], content=b"x", headers={"X-Forwarded-For": "7.7.7.7"}
            )
        other = await client.post(
            ep["webhook_url"], content=b"x", headers={"X-Forwarded-For": "6.6.6.6"}
        )
        assert other.status_code == 200  # different source IP: separate bucket

    async def test_keys_do_not_share_across_endpoints(self, limited_env):
        _app, client = limited_env
        ep1 = (await client.post("/api/endpoints", json={"name": "a"})).json()["data"]
        ep2 = (await client.post("/api/endpoints", json={"name": "b"})).json()["data"]
        for _ in range(3):
            await client.post(
                ep1["webhook_url"], content=b"x", headers={"X-Forwarded-For": "5.5.5.5"}
            )
        resp = await client.post(
            ep2["webhook_url"], content=b"x", headers={"X-Forwarded-For": "5.5.5.5"}
        )
        assert resp.status_code == 200


class TestStateBounds:
    def test_expired_key_dropped_on_access(self):
        clock = FakeClock()
        limiter = SlidingWindowRateLimiter(2, 60, clock=clock)
        limiter.check("k")
        assert "k" in limiter._hits
        clock.advance(61)
        limiter.check("k")  # access after expiry purges and re-creates
        assert list(limiter._hits["k"]) == [clock.now]

    def test_state_bounded_under_key_rotation(self, monkeypatch):
        """Attackers rotating source IPs must not grow limiter memory."""
        import app.services.rate_limit as rl_mod

        monkeypatch.setattr(rl_mod, "MAX_TRACKED_KEYS", 10)
        clock = FakeClock()
        limiter = SlidingWindowRateLimiter(1_000_000, 60, clock=clock)
        for i in range(500):
            limiter.check(f"rotating-{i}")
        assert len(limiter._hits) <= 10
