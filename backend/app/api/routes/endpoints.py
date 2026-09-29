"""Management API for webhook endpoints."""

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession, require_admin
from app.config import Settings
from app.errors import EndpointNotFound, InvalidInput
from app.models import WebhookEndpoint, WebhookRequest
from app.schemas import (
    EndpointCreate,
    EndpointOut,
    EndpointUpdate,
    Envelope,
    SignatureStatusInfo,
)
from app.services import crypto
from app.util import as_utc, utcnow

router = APIRouter(dependencies=[Depends(require_admin)])


def build_webhook_url(settings: Settings, request: Request, public_id: str) -> str:
    base = settings.base_url.rstrip("/") if settings.base_url else str(request.base_url).rstrip("/")
    return f"{base}/hook/{public_id}"


def endpoint_status(endpoint: WebhookEndpoint) -> str:
    if not endpoint.enabled:
        return "disabled"
    if as_utc(endpoint.expires_at) < utcnow():
        return "expired"
    return "active"


_last_request_sq = (
    select(func.max(WebhookRequest.received_at))
    .where(WebhookRequest.endpoint_id == WebhookEndpoint.id)
    .correlate(WebhookEndpoint)
    .scalar_subquery()
)


def to_endpoint_out(
    endpoint: WebhookEndpoint,
    settings: Settings,
    request: Request,
    last_request_at=None,
) -> EndpointOut:
    return EndpointOut(
        id=endpoint.id,
        name=endpoint.name,
        public_id=endpoint.public_id,
        webhook_url=build_webhook_url(settings, request, endpoint.public_id),
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
        expires_at=endpoint.expires_at,
        enabled=endpoint.enabled,
        max_requests=endpoint.max_requests,
        request_count=endpoint.request_count,
        request_retention_hours=endpoint.request_retention_hours,
        status=endpoint_status(endpoint),  # type: ignore[arg-type]
        last_request_at=last_request_at,
        response_status=endpoint.response_status,
        response_content_type=endpoint.response_content_type,
        response_body=endpoint.response_body,
        response_delay_ms=endpoint.response_delay_ms,
        replay_target_url=endpoint.replay_target_url,
        signature=SignatureStatusInfo(
            enabled=endpoint.signature_enabled,
            header=endpoint.signature_header,
            algorithm=endpoint.signature_algorithm,
            encoding=endpoint.signature_encoding,
            configured=bool(endpoint.signature_secret_encrypted),
        ),
        ingest_token_configured=bool(endpoint.ingest_token_hash),
    )


async def get_endpoint_or_404(session: AsyncSession, endpoint_id: int) -> WebhookEndpoint:
    endpoint = await session.get(WebhookEndpoint, endpoint_id)
    if endpoint is None:
        raise EndpointNotFound()
    return endpoint


async def load_with_last_request(
    session: AsyncSession, endpoint: WebhookEndpoint
) -> tuple[WebhookEndpoint, object]:
    last_request_at = await session.scalar(
        select(func.max(WebhookRequest.received_at)).where(
            WebhookRequest.endpoint_id == endpoint.id
        )
    )
    return endpoint, last_request_at


@router.get("/endpoints", response_model=Envelope[list[EndpointOut]])
async def list_endpoints(request: Request, session: DbSession):
    settings: Settings = request.app.state.settings
    rows = (
        await session.execute(
            select(WebhookEndpoint, _last_request_sq).order_by(
                WebhookEndpoint.created_at.desc(), WebhookEndpoint.id.desc()
            )
        )
    ).all()
    return Envelope(data=[to_endpoint_out(e, settings, request, last) for e, last in rows])


@router.post("/endpoints", response_model=Envelope[EndpointOut], status_code=201)
async def create_endpoint(payload: EndpointCreate, request: Request, session: DbSession):
    settings: Settings = request.app.state.settings
    endpoint = WebhookEndpoint(
        name=payload.name,
        public_id=secrets.token_urlsafe(16),  # ~128 bits of entropy, not enumerable
        expires_at=utcnow() + timedelta(hours=payload.ttl_hours),
        enabled=True,
        max_requests=payload.max_requests,
        request_retention_hours=payload.request_retention_hours,
        response_status=payload.response_status,
        response_content_type=payload.response_content_type,
        response_body=payload.response_body,
        response_delay_ms=payload.response_delay_ms,
        replay_target_url=payload.replay_target_url,
    )
    if payload.signature and payload.signature.enabled:
        if payload.signature.secret is None:
            raise InvalidInput("A signature secret is required when enabling verification")
        endpoint.signature_enabled = True
        endpoint.signature_header = payload.signature.header
        endpoint.signature_algorithm = payload.signature.algorithm
        endpoint.signature_encoding = payload.signature.encoding
        endpoint.signature_secret_encrypted = crypto.encrypt_secret(
            payload.signature.secret.get_secret_value(), settings.secret_key
        )
    if payload.ingest_token is not None:
        endpoint.ingest_token_hash = crypto.hash_token(payload.ingest_token.get_secret_value())

    session.add(endpoint)
    await session.commit()
    await session.refresh(endpoint)
    return Envelope(data=to_endpoint_out(endpoint, settings, request))


@router.get("/endpoints/{endpoint_id}", response_model=Envelope[EndpointOut])
async def get_endpoint(endpoint_id: int, request: Request, session: DbSession):
    endpoint = await get_endpoint_or_404(session, endpoint_id)
    settings: Settings = request.app.state.settings
    _, last_request_at = await load_with_last_request(session, endpoint)
    return Envelope(data=to_endpoint_out(endpoint, settings, request, last_request_at))


@router.patch("/endpoints/{endpoint_id}", response_model=Envelope[EndpointOut])
async def update_endpoint(
    endpoint_id: int, payload: EndpointUpdate, request: Request, session: DbSession
):
    settings: Settings = request.app.state.settings
    endpoint = await get_endpoint_or_404(session, endpoint_id)

    if payload.name is not None:
        stripped = payload.name.strip()
        if not stripped:
            raise InvalidInput("name must not be blank")
        endpoint.name = stripped
    if payload.enabled is not None:
        endpoint.enabled = payload.enabled
    if payload.ttl_hours is not None:
        endpoint.expires_at = utcnow() + timedelta(hours=payload.ttl_hours)
    if payload.max_requests is not None:
        endpoint.max_requests = payload.max_requests
    if "request_retention_hours" in payload.model_fields_set:
        endpoint.request_retention_hours = payload.request_retention_hours
    if payload.response_status is not None:
        endpoint.response_status = payload.response_status
    if payload.response_body is not None:
        endpoint.response_body = payload.response_body
    if payload.response_content_type is not None:
        endpoint.response_content_type = payload.response_content_type
    if payload.response_delay_ms is not None:
        endpoint.response_delay_ms = payload.response_delay_ms
    if "replay_target_url" in payload.model_fields_set:
        endpoint.replay_target_url = payload.replay_target_url

    if payload.signature is not None:
        endpoint.signature_enabled = payload.signature.enabled
        endpoint.signature_header = payload.signature.header
        endpoint.signature_algorithm = payload.signature.algorithm
        endpoint.signature_encoding = payload.signature.encoding
        if payload.signature.secret is not None:
            endpoint.signature_secret_encrypted = crypto.encrypt_secret(
                payload.signature.secret.get_secret_value(), settings.secret_key
            )
        if payload.signature.enabled and endpoint.signature_secret_encrypted is None:
            raise InvalidInput("A signature secret is required when enabling verification")

    if payload.ingest_token is not None:
        endpoint.ingest_token_hash = crypto.hash_token(payload.ingest_token.get_secret_value())
    elif payload.remove_ingest_token:
        endpoint.ingest_token_hash = None

    await session.commit()
    await session.refresh(endpoint)
    _, last_request_at = await load_with_last_request(session, endpoint)
    return Envelope(data=to_endpoint_out(endpoint, settings, request, last_request_at))


@router.delete("/endpoints/{endpoint_id}", response_model=Envelope[EndpointOut])
async def delete_endpoint(endpoint_id: int, request: Request, session: DbSession):
    endpoint = await get_endpoint_or_404(session, endpoint_id)
    settings: Settings = request.app.state.settings
    _, last_request_at = await load_with_last_request(session, endpoint)
    out = to_endpoint_out(endpoint, settings, request, last_request_at)
    await session.delete(endpoint)  # requests and replays cascade
    await session.commit()
    return Envelope(data=out)
