import pytest


@pytest.mark.asyncio
async def test_health_ok(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "ok"
    assert data["version"] == "0.2.0"
    assert data["database"] == "ok"


async def test_health_requires_no_token(client):
    client.headers.pop("Authorization")
    resp = await client.get("/api/health")
    assert resp.status_code == 200
