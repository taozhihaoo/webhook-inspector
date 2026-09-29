"""Shared pytest fixtures.

Tests are deterministic: they run against an in-memory SQLite database, use
httpx MockTransport for replay HTTP, fake DNS resolvers, and never touch the
real internet. The suite also passes against a real PostgreSQL server by
setting TEST_DATABASE_URL before running.
"""

import os

os.environ.setdefault("ADMIN_API_TOKEN", "test-admin-token")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests")
os.environ.setdefault("APP_ENV", "test")

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from app.config import Settings
from app.db_base import Base
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

ADMIN_TOKEN = "test-admin-token"


def make_settings(**overrides) -> Settings:
    defaults = dict(
        app_env="test",
        admin_api_token=ADMIN_TOKEN,
        secret_key="test-secret-key-for-unit-tests",
        # Set TEST_DATABASE_URL (e.g. PostgreSQL) to run the suite against a
        # real server; the default in-memory SQLite keeps runs deterministic.
        database_url=os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite://"),
        base_url="http://testserver",
        rate_limit_requests=1000,
        rate_limit_window_seconds=60,
        cleanup_interval_seconds=3600,
        cleanup_grace_hours=24,
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


async def create_tables(application) -> None:
    async with application.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables(application) -> None:
    async with application.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def app() -> AsyncIterator:
    application = create_app(make_settings())
    await create_tables(application)
    yield application
    # Keeps PostgreSQL runs isolated between tests (SQLite in-memory just dies).
    await drop_tables(application)
    await application.state.engine.dispose()


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        ac.headers["Authorization"] = f"Bearer {ADMIN_TOKEN}"
        yield ac


@pytest.fixture
async def make_endpoint(client) -> AsyncIterator:
    async def _create(**overrides) -> dict:
        payload = {"name": overrides.pop("name", "test-endpoint")}
        payload.update(overrides)
        resp = await client.post("/api/endpoints", json=payload)
        assert resp.status_code == 201, resp.text
        return resp.json()["data"]

    return _create


@pytest.fixture
async def db_session(app) -> AsyncIterator[AsyncSession]:
    """Direct database access for tests that need to simulate time/state."""
    async with app.state.session_factory() as session:
        yield session
