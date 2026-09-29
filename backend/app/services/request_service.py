"""Request history: listing, search, pagination and deletion."""

from datetime import datetime

from sqlalchemy import Text, cast, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.errors import EndpointNotFound, RequestNotFound
from app.models import WebhookEndpoint, WebhookRequest
from app.schemas import Page, RequestDetail, RequestSummary


async def _endpoint_exists(session: AsyncSession, endpoint_id: int) -> None:
    if await session.get(WebhookEndpoint, endpoint_id) is None:
        raise EndpointNotFound()


def build_query(
    endpoint_id: int,
    *,
    method: str | None = None,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> Select:
    stmt = (
        select(WebhookRequest)
        .where(WebhookRequest.endpoint_id == endpoint_id)
        .order_by(WebhookRequest.id.desc())
    )
    if method:
        stmt = stmt.where(WebhookRequest.method == method.upper())
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                WebhookRequest.path.ilike(pattern),
                WebhookRequest.body_text.ilike(pattern),
                cast(WebhookRequest.headers, Text).ilike(pattern),
                cast(WebhookRequest.query_parameters, Text).ilike(pattern),
            )
        )
    if date_from is not None:
        stmt = stmt.where(WebhookRequest.received_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(WebhookRequest.received_at <= date_to)
    return stmt


async def list_requests(
    session: AsyncSession,
    endpoint_id: int,
    *,
    method: str | None,
    search: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    page: int,
    page_size: int,
) -> Page[RequestSummary]:
    await _endpoint_exists(session, endpoint_id)
    stmt = build_query(
        endpoint_id, method=method, search=search, date_from=date_from, date_to=date_to
    )
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await session.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all()
    return Page(
        items=[RequestSummary.model_validate(r) for r in rows],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


async def get_request_detail(session: AsyncSession, request_id: int) -> RequestDetail:
    record = await session.get(WebhookRequest, request_id)
    if record is None:
        raise RequestNotFound()
    return RequestDetail.model_validate(record)


async def delete_request(session: AsyncSession, request_id: int) -> None:
    record = await session.get(WebhookRequest, request_id)
    if record is None:
        raise RequestNotFound()
    await session.delete(record)  # replay records cascade
    await session.commit()


async def clear_requests(session: AsyncSession, endpoint_id: int) -> int:
    await _endpoint_exists(session, endpoint_id)
    result = await session.execute(
        delete(WebhookRequest).where(WebhookRequest.endpoint_id == endpoint_id)
    )
    await session.commit()
    return result.rowcount or 0
