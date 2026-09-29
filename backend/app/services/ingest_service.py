"""Ingest pipeline: receive a webhook, record it, answer with the configured response.

Guarantees:
- the raw body is always preserved first; a JSON parse failure never loses data
- oversized bodies are rejected with 413 (a stub row records the attempt)
- expired/disabled endpoints reject with explicit error codes (recorded too)
- responses always use the endpoint's configured status/body/content-type
"""

import asyncio
import json
import logging
import time

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import JSONResponse, Response

from app.config import Settings
from app.models import IngestAuthStatus, SignatureStatus, WebhookEndpoint, WebhookRequest
from app.services import crypto
from app.services.signature import verify_signature
from app.util import as_utc, decode_lossy, utcnow

logger = logging.getLogger("webhook_inspector.ingest")

JSON_CONTENT_TYPES = ("application/json", "text/json", "application/problem+json")


def error_response(
    status_code: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}}, status_code=status_code, headers=headers
    )


def client_ip(settings: Settings, request: Request) -> str | None:
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


async def read_body_capped(request: Request, cap: int) -> tuple[bytes | None, int]:
    """Read the body up to ``cap`` bytes.

    Returns ``(body, size)``; ``body`` is ``None`` when the request exceeds the
    cap (``size`` is then the declared or observed size).
    """
    declared = request.headers.get("content-length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError:
            declared_size = None  # malformed header; fall through to streaming read
        if declared_size is not None and declared_size > cap:
            return None, declared_size

    buffer = bytearray()
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > cap:
            return None, total
        buffer.extend(chunk)
    return bytes(buffer), total


async def prune_history(session: AsyncSession, endpoint: WebhookEndpoint) -> None:
    """Keep only the newest ``max_requests`` rows (rolling history window)."""
    # The id at offset max_requests (0-based) is the (max_requests+1)-th newest;
    # everything at or below it gets deleted, leaving exactly max_requests rows.
    cutoff_id = await session.scalar(
        select(WebhookRequest.id)
        .where(WebhookRequest.endpoint_id == endpoint.id)
        .order_by(WebhookRequest.id.desc())
        .offset(endpoint.max_requests)
        .limit(1)
    )
    if cutoff_id is not None:
        await session.execute(
            delete(WebhookRequest).where(
                WebhookRequest.endpoint_id == endpoint.id,
                WebhookRequest.id <= cutoff_id,
            )
        )


def _headers_snapshot(request: Request) -> dict[str, str]:
    return dict(request.headers)


def _maybe_parse_json(content_type: str | None, body_text: str | None) -> object | None:
    """Parse JSON only when it is plausible; failure keeps the raw body intact."""
    if not body_text:
        return None
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    looks_like_json = media_type in JSON_CONTENT_TYPES
    if not media_type:
        stripped = body_text.lstrip()
        looks_like_json = stripped[:1] in ("{", "[")
    if not looks_like_json:
        return None
    try:
        return json.loads(body_text)
    except ValueError:
        return None


async def _record_request(
    session: AsyncSession,
    endpoint: WebhookEndpoint,
    request: Request,
    ip: str | None,
    response_status: int,
    started: float,
    *,
    body: bytes | None = None,
    body_size: int = 0,
    signature_status: SignatureStatus = SignatureStatus.not_configured,
    ingest_auth_status: IngestAuthStatus = IngestAuthStatus.not_configured,
) -> WebhookRequest:
    body_text = decode_lossy(body)
    record = WebhookRequest(
        endpoint_id=endpoint.id,
        received_at=utcnow(),
        method=request.method,
        path=request.url.path,
        query_parameters=dict(request.query_params),
        headers=_headers_snapshot(request),
        body_raw=body,
        body_text=body_text,
        body_json=_maybe_parse_json(request.headers.get("content-type"), body_text),
        content_type=request.headers.get("content-type"),
        body_size=body_size,
        source_ip=ip,
        processing_duration_ms=int((time.perf_counter() - started) * 1000),
        signature_status=signature_status,
        ingest_auth_status=ingest_auth_status,
        response_status=response_status,
    )
    session.add(record)
    await session.commit()
    return record


async def handle_ingest(state, request: Request, public_id: str) -> Response:
    settings: Settings = state.settings
    session_factory: async_sessionmaker[AsyncSession] = state.session_factory
    started = time.perf_counter()

    async with session_factory() as session:
        endpoint = await session.scalar(
            select(WebhookEndpoint).where(WebhookEndpoint.public_id == public_id)
        )
        if endpoint is None:
            return error_response(404, "endpoint_not_found", "Webhook endpoint not found.")

        ip = client_ip(settings, request)

        # Rate limiting happens first: cheap rejection before touching the body.
        limit_result = state.rate_limiter.check(f"{endpoint.id}:{ip or '-'}")
        rate_headers = {
            "X-RateLimit-Limit": str(limit_result.limit),
            "X-RateLimit-Remaining": str(limit_result.remaining),
            "X-RateLimit-Reset": str(limit_result.reset_epoch),
        }
        if not limit_result.allowed:
            rate_headers["Retry-After"] = str(limit_result.retry_after_seconds)
            return error_response(
                429,
                "rate_limit_exceeded",
                "Too many requests to this endpoint. Retry later.",
                rate_headers,
            )

        if as_utc(endpoint.expires_at) < utcnow():
            await _record_request(session, endpoint, request, ip, 410, started)
            return error_response(
                410, "endpoint_expired", "This webhook endpoint has expired.", rate_headers
            )
        if not endpoint.enabled:
            await _record_request(session, endpoint, request, ip, 409, started)
            return error_response(
                409, "endpoint_disabled", "This webhook endpoint is disabled.", rate_headers
            )

        body, body_size = await read_body_capped(request, settings.max_body_size)
        if body is None:
            await _record_request(
                session, endpoint, request, ip, 413, started, body_size=body_size
            )
            return error_response(
                413,
                "payload_too_large",
                f"Request body exceeds the {settings.max_body_size} byte limit.",
                rate_headers,
            )

        # Optional per-endpoint ingest token (X-Webhook-Token).
        ingest_auth_status = IngestAuthStatus.not_configured
        if endpoint.ingest_token_hash:
            provided = request.headers.get("x-webhook-token", "")
            token_ok = bool(provided) and crypto.secrets_equal(
                crypto.hash_token(provided), endpoint.ingest_token_hash
            )
            ingest_auth_status = IngestAuthStatus.valid if token_ok else IngestAuthStatus.invalid
            if not token_ok:
                await _record_request(
                    session,
                    endpoint,
                    request,
                    ip,
                    401,
                    started,
                    body=body,
                    body_size=body_size,
                    ingest_auth_status=ingest_auth_status,
                )
                return error_response(
                    401,
                    "invalid_ingest_token",
                    "Missing or invalid X-Webhook-Token.",
                    rate_headers,
                )

        # Generic HMAC signature verification over the raw body.
        signature_status = SignatureStatus.not_configured
        if (
            endpoint.signature_enabled
            and endpoint.signature_header
            and endpoint.signature_secret_encrypted
        ):
            provided_signature = request.headers.get(endpoint.signature_header)
            if not provided_signature:
                signature_status = SignatureStatus.invalid
            else:
                try:
                    secret = crypto.decrypt_secret(
                        endpoint.signature_secret_encrypted, settings.secret_key
                    )
                    valid = verify_signature(
                        secret,
                        body,
                        provided_signature,
                        endpoint.signature_algorithm or "hmac-sha256",
                        endpoint.signature_encoding or "hex",
                    )
                    signature_status = (
                        SignatureStatus.verified if valid else SignatureStatus.invalid
                    )
                except Exception:
                    logger.exception("Signature verification error (endpoint %s)", endpoint.id)
                    signature_status = SignatureStatus.error

        record = WebhookRequest(
            endpoint_id=endpoint.id,
            received_at=utcnow(),
            method=request.method,
            path=request.url.path,
            query_parameters=dict(request.query_params),
            headers=_headers_snapshot(request),
            body_raw=body,
            body_text=decode_lossy(body),
            body_json=_maybe_parse_json(request.headers.get("content-type"), decode_lossy(body)),
            content_type=request.headers.get("content-type"),
            body_size=body_size,
            source_ip=ip,
            processing_duration_ms=int((time.perf_counter() - started) * 1000),
            signature_status=signature_status,
            ingest_auth_status=ingest_auth_status,
            response_status=endpoint.response_status,
            replayable=True,
        )
        session.add(record)
        endpoint.request_count += 1
        await session.flush()
        await prune_history(session, endpoint)
        await session.commit()

        state.broker.publish(
            endpoint.id,
            {
                "endpoint_id": endpoint.id,
                "request_id": record.id,
                "method": record.method,
                "received_at": record.received_at.isoformat(),
                "body_size": record.body_size,
                "signature_status": signature_status.value,
                "ingest_auth_status": ingest_auth_status.value,
                "response_status": endpoint.response_status,
            },
        )

    if endpoint.response_delay_ms > 0:
        await asyncio.sleep(min(endpoint.response_delay_ms, 10_000) / 1000)

    if request.method == "HEAD":
        return Response(status_code=endpoint.response_status, headers=rate_headers)
    return Response(
        content=endpoint.response_body.encode("utf-8"),
        status_code=endpoint.response_status,
        media_type=endpoint.response_content_type,
        headers=rate_headers,
    )
