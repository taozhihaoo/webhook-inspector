"""TTL expiry and the background cleanup worker."""

from datetime import timedelta

from app.models import ReplayRecord, ReplayStatus, WebhookEndpoint, WebhookRequest
from app.services.cleanup_service import CleanupService
from app.util import utcnow


async def set_expiry(app, endpoint_id: int, *, hours_from_now: float) -> None:
    from sqlalchemy import update

    async with app.state.session_factory() as session:
        await session.execute(
            update(WebhookEndpoint)
            .where(WebhookEndpoint.id == endpoint_id)
            .values(expires_at=utcnow() + timedelta(hours=hours_from_now))
        )
        await session.commit()


async def make_service(app) -> CleanupService:
    return CleanupService(app.state.session_factory, app.state.settings)


class TestExpiryBehavior:
    async def test_expired_endpoint_rejects_ingest(self, client, make_endpoint, app):
        ep = await make_endpoint(ttl_hours=1)
        await set_expiry(app, ep["id"], hours_from_now=-1)
        resp = await client.post(ep["webhook_url"], json={"late": True})
        assert resp.status_code == 410

    async def test_future_expiry_accepts_ingest(self, client, make_endpoint, app):
        ep = await make_endpoint(ttl_hours=1)
        await set_expiry(app, ep["id"], hours_from_now=2)
        resp = await client.post(ep["webhook_url"], json={"on_time": True})
        assert resp.status_code == 200


class TestCleanupWorker:
    async def test_deletes_expired_beyond_grace_with_cascade(
        self, client, make_endpoint, app, db_session
    ):
        ep = await make_endpoint(ttl_hours=1)
        await client.post(ep["webhook_url"], json={"a": 1})

        # Attach a replay record so we can verify the full cascade.
        lst = (await client.get(f"/api/endpoints/{ep['id']}/requests")).json()["data"]
        request_id = lst["items"][0]["id"]
        db_session.add(
            ReplayRecord(
                original_request_id=request_id,
                target_url="https://t.example/x",
                method="POST",
                headers={},
                status=ReplayStatus.success,
            )
        )
        await db_session.commit()

        # Expire far beyond the 24h grace period.
        await set_expiry(app, ep["id"], hours_from_now=-48)
        service = await make_service(app)
        stats = await service.run_once()
        assert stats["endpoints_deleted"] == 1

        # Endpoint, requests and replay records are all gone.
        assert (await client.get(f"/api/endpoints/{ep['id']}")).status_code == 404
        assert (await client.get(f"/api/requests/{request_id}")).status_code == 404
        from sqlalchemy import func, select

        async with app.state.session_factory() as session:
            replay_count = await session.scalar(select(func.count()).select_from(ReplayRecord))
        assert replay_count == 0

    async def test_keeps_expired_within_grace(self, client, make_endpoint, app):
        ep = await make_endpoint(ttl_hours=1)
        await set_expiry(app, ep["id"], hours_from_now=-2)  # within 24h grace
        service = await make_service(app)
        stats = await service.run_once()
        assert stats["endpoints_deleted"] == 0
        assert (await client.get(f"/api/endpoints/{ep['id']}")).status_code == 200

    async def test_run_once_is_idempotent(self, client, make_endpoint, app):
        ep = await make_endpoint(ttl_hours=1)
        await set_expiry(app, ep["id"], hours_from_now=-72)
        service = await make_service(app)
        first = await service.run_once()
        second = await service.run_once()
        assert first["endpoints_deleted"] == 1
        assert second["endpoints_deleted"] == 0

    async def test_request_retention_prunes_old_rows(self, client, make_endpoint, app, db_session):
        ep = await make_endpoint(request_retention_hours=1)
        old = WebhookRequest(
            endpoint_id=ep["id"],
            received_at=utcnow() - timedelta(hours=3),
            method="POST",
            path=f"/hook/{ep['public_id']}",
            query_parameters={},
            headers={},
            body_size=0,
            response_status=200,
        )
        fresh = WebhookRequest(
            endpoint_id=ep["id"],
            received_at=utcnow(),
            method="POST",
            path=f"/hook/{ep['public_id']}",
            query_parameters={},
            headers={},
            body_size=0,
            response_status=200,
        )
        db_session.add_all([old, fresh])
        await db_session.commit()
        old_id, fresh_id = old.id, fresh.id

        service = await make_service(app)
        stats = await service.run_once()
        assert stats["requests_deleted"] == 1
        assert (await client.get(f"/api/requests/{old_id}")).status_code == 404
        assert (await client.get(f"/api/requests/{fresh_id}")).status_code == 200

    async def test_endpoints_without_retention_keep_old_requests(
        self, client, make_endpoint, app, db_session
    ):
        ep = await make_endpoint()  # no request_retention_hours
        old = WebhookRequest(
            endpoint_id=ep["id"],
            received_at=utcnow() - timedelta(hours=72),
            method="GET",
            path=f"/hook/{ep['public_id']}",
            query_parameters={},
            headers={},
            body_size=0,
            response_status=200,
        )
        db_session.add(old)
        await db_session.commit()
        service = await make_service(app)
        await service.run_once()
        assert (await client.get(f"/api/requests/{old.id}")).status_code == 200
