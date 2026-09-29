"""Replay: resend a captured request (optionally edited) to a target URL.

Every replay produces a persisted ReplayRecord — including blocked and timed
out attempts — so the audit trail shows target URL, timestamp and outcome.

SSRF protection lives in ``app.services.ssrf``; redirects are followed
manually so each hop is re-validated.
"""

import logging
import time
from collections.abc import Callable
from urllib.parse import urljoin

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.errors import InvalidInput, RequestNotFound
from app.models import ReplayRecord, ReplayStatus, WebhookEndpoint, WebhookRequest
from app.schemas import CloneOut, ReplayCreate
from app.services.ssrf import UnsafeTargetError, default_resolver, validate_target

logger = logging.getLogger("webhook_inspector.replay")

# Hop-by-hop / recomputed headers must not be copied onto the replay.
STRIPPED_HEADERS = {"host", "content-length"}

REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def _truncate_headers(
    headers: dict[str, str], *, max_headers: int = 50, max_value: int = 2048
) -> dict[str, str]:
    return {
        str(k)[:200]: str(v)[:max_value]
        for k, v in list(headers.items())[:max_headers]
    }


async def _read_capped(response: httpx.Response, cap: int) -> str:
    chunks = bytearray()
    async for chunk in response.aiter_bytes():
        chunks.extend(chunk)
        if len(chunks) >= cap:
            break
    text = bytes(chunks[:cap]).decode("utf-8", errors="replace")
    if len(chunks) >= cap:
        text += f"\n... [truncated at {cap} bytes]"
    return text


class ReplayService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ):
        self.session_factory = session_factory
        self.settings = settings
        # Injectable for tests (fake DNS, mock transport).
        self.resolver: Callable = default_resolver
        self.client_factory: Callable[[], httpx.AsyncClient] = self._default_client

    def _default_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(self.settings.replay_timeout_seconds, connect=5.0),
        )

    async def execute(self, original_request_id: int, params: ReplayCreate) -> ReplayRecord:
        async with self.session_factory() as session:
            original = await session.get(WebhookRequest, original_request_id)
            if original is None:
                raise RequestNotFound()
            endpoint = await session.get(WebhookEndpoint, original.endpoint_id)
            target = params.target_url or (endpoint.replay_target_url if endpoint else None)
            if not target:
                raise InvalidInput(
                    "No replay target: pass target_url or configure one on the endpoint.",
                    code="no_replay_target",
                )
            method = (params.method or original.method or "POST").upper()
            source_headers = (
                params.headers if params.headers is not None else (original.headers or {})
            )
            headers = {
                k: v for k, v in source_headers.items() if k.lower() not in STRIPPED_HEADERS
            }
            body = (
                params.body_text.encode("utf-8")
                if params.body_text is not None
                else (original.body_raw or b"")
            )
            record = ReplayRecord(
                original_request_id=original.id,
                target_url=target[:2000],
                method=method,
                headers=headers,
                body=body or None,
                status=ReplayStatus.error,
            )
            session.add(record)
            await session.commit()
            record_id = record.id

        return await self._perform(record_id, target, method, headers, body)

    async def _perform(
        self,
        record_id: int,
        target: str,
        method: str,
        headers: dict[str, str],
        body: bytes,
    ) -> ReplayRecord:
        started = time.perf_counter()
        status = ReplayStatus.error
        response_status: int | None = None
        response_headers: dict[str, str] | None = None
        preview: str | None = None
        error_message: str | None = None
        duration_ms: int | None = None

        client = self.client_factory()
        try:
            url = target
            current_method = method
            current_body = body
            hops = 0
            while True:
                await validate_target(
                    url,
                    allow_http=self.settings.allow_http_replay,
                    allow_private=self.settings.replay_allow_private_networks,
                    resolver=self.resolver,
                )
                response = await client.request(
                    current_method,
                    url,
                    headers=headers,
                    content=current_body if current_method not in {"GET", "HEAD"} else None,
                )
                if (
                    response.status_code in REDIRECT_STATUSES
                    and hops < self.settings.replay_max_redirects
                    and "location" in response.headers
                ):
                    # Re-validate every hop: a public URL must not redirect inside.
                    url = urljoin(url, response.headers["location"])
                    if response.status_code in {301, 302, 303} and current_method != "HEAD":
                        current_method, current_body = "GET", b""
                    hops += 1
                    await response.aclose()
                    continue
                duration_ms = int((time.perf_counter() - started) * 1000)
                status = ReplayStatus.success  # the HTTP exchange itself completed
                response_status = response.status_code
                response_headers = _truncate_headers(dict(response.headers))
                preview = await _read_capped(response, self.settings.replay_max_response_bytes)
                await response.aclose()
                break
        except UnsafeTargetError as exc:
            logger.info("Replay blocked: %s", exc.reason)
            status = ReplayStatus.blocked
            error_message = f"Blocked by SSRF protection: {exc.reason}"
        except httpx.TimeoutException:
            status = ReplayStatus.timeout
            error_message = (
                f"Target did not respond within {self.settings.replay_timeout_seconds:g}s"
            )
        except httpx.HTTPError as exc:
            status = ReplayStatus.error
            error_message = f"Replay failed: {type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001 - never lose the audit record
            logger.exception("Unexpected replay failure")
            status = ReplayStatus.error
            error_message = f"Replay failed: {type(exc).__name__}"
        finally:
            await client.aclose()

        async with self.session_factory() as session:
            record = await session.get(ReplayRecord, record_id)
            record.status = status
            record.response_status = response_status
            record.response_headers = response_headers
            record.response_body_preview = preview
            record.duration_ms = duration_ms
            record.error_message = error_message
            await session.commit()
            return record


async def list_replays(session: AsyncSession, request_id: int) -> list[ReplayRecord]:
    result = await session.scalars(
        select(ReplayRecord)
        .where(ReplayRecord.original_request_id == request_id)
        .order_by(ReplayRecord.id.desc())
    )
    return list(result)


async def clone_request(session: AsyncSession, request_id: int) -> CloneOut:
    record = await session.get(WebhookRequest, request_id)
    if record is None:
        raise RequestNotFound()
    endpoint = await session.get(WebhookEndpoint, record.endpoint_id)
    return CloneOut(
        target_url=endpoint.replay_target_url if endpoint else None,
        method=record.method,
        headers=dict(record.headers or {}),
        body_text=record.body_text,
        content_type=record.content_type,
        query_parameters=dict(record.query_parameters or {}),
    )
