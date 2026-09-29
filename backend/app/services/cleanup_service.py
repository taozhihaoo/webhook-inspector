"""Background cleanup worker.

Deletes, on a fixed interval:
- endpoints whose ``expires_at`` is older than ``cleanup_grace_hours``
  (requests and replay records cascade)
- requests older than their endpoint's per-endpoint ``request_retention_hours``
- rows beyond an endpoint's ``max_requests`` (safety net alongside the
  ingest-time prune)

The worker is idempotent, testable (``run_once``) and shuts down gracefully
via task cancellation.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import WebhookEndpoint, WebhookRequest
from app.services.ingest_service import prune_history
from app.util import as_utc, utcnow

logger = logging.getLogger("webhook_inspector.cleanup")


class CleanupService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: Settings):
        self.session_factory = session_factory
        self.settings = settings

    async def run_once(self) -> dict[str, int]:
        now = utcnow()
        stats = {"endpoints_deleted": 0, "requests_deleted": 0}

        async with self.session_factory() as session:
            # 1. Endpoints expired beyond the retention grace period.
            cutoff = now - timedelta(hours=self.settings.cleanup_grace_hours)
            result = await session.execute(
                delete(WebhookEndpoint).where(WebhookEndpoint.expires_at < cutoff)
            )
            stats["endpoints_deleted"] = result.rowcount or 0
            await session.commit()

            # 2. Per-endpoint request retention.
            endpoints = (
                await session.scalars(
                    select(WebhookEndpoint).where(
                        WebhookEndpoint.request_retention_hours.is_not(None)
                    )
                )
            ).all()
            for endpoint in endpoints:
                cutoff = now - timedelta(hours=endpoint.request_retention_hours or 0)
                result = await session.execute(
                    delete(WebhookRequest).where(
                        WebhookRequest.endpoint_id == endpoint.id,
                        WebhookRequest.received_at < cutoff,
                    )
                )
                stats["requests_deleted"] += result.rowcount or 0
            await session.commit()

            # 3. Enforce max_requests on every endpoint (safety net).
            endpoints = (await session.scalars(select(WebhookEndpoint))).all()
            for endpoint in endpoints:
                await prune_history(session, endpoint)
            await session.commit()

        if stats["endpoints_deleted"] or stats["requests_deleted"]:
            logger.info(
                "Cleanup removed %d endpoints and %d requests",
                stats["endpoints_deleted"],
                stats["requests_deleted"],
            )
        return stats

    async def run_forever(self) -> None:
        logger.info(
            "Cleanup worker started (interval: %ds)", self.settings.cleanup_interval_seconds
        )
        try:
            while True:
                await asyncio.sleep(self.settings.cleanup_interval_seconds)
                try:
                    await self.run_once()
                except Exception:
                    logger.exception("Cleanup run failed; will retry next interval")
        except asyncio.CancelledError:
            logger.info("Cleanup worker stopped")
            raise


def endpoint_expired(endpoint: WebhookEndpoint, now=None) -> bool:
    return as_utc(endpoint.expires_at) < (now or utcnow())
