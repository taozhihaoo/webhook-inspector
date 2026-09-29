"""Request history & replay management API."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession, require_admin
from app.errors import EndpointNotFound
from app.models import WebhookEndpoint
from app.schemas import (
    CloneOut,
    DeleteOut,
    Envelope,
    Page,
    ReplayCreate,
    ReplayRecordOut,
    RequestDetail,
    RequestSummary,
)
from app.services import replay_service, request_service

router = APIRouter(dependencies=[Depends(require_admin)])


async def _endpoint_exists(session: AsyncSession, endpoint_id: int) -> None:
    if await session.get(WebhookEndpoint, endpoint_id) is None:
        raise EndpointNotFound()


@router.get(
    "/endpoints/{endpoint_id}/requests",
    response_model=Envelope[Page[RequestSummary]],
)
async def list_requests(
    endpoint_id: int,
    session: DbSession,
    method: Annotated[str | None, Query(max_length=10)] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    result = await request_service.list_requests(
        session,
        endpoint_id,
        method=method,
        search=search,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    return Envelope(data=result)


@router.delete("/endpoints/{endpoint_id}/requests", response_model=Envelope[DeleteOut])
async def clear_requests(endpoint_id: int, session: DbSession):
    count = await request_service.clear_requests(session, endpoint_id)
    return Envelope(data=DeleteOut(deleted=True, count=count))


@router.get("/requests/{request_id}", response_model=Envelope[RequestDetail])
async def get_request(request_id: int, session: DbSession):
    return Envelope(data=await request_service.get_request_detail(session, request_id))


@router.delete("/requests/{request_id}", response_model=Envelope[DeleteOut])
async def delete_request(request_id: int, session: DbSession):
    await request_service.delete_request(session, request_id)
    return Envelope(data=DeleteOut(deleted=True))


@router.post("/requests/{request_id}/clone", response_model=Envelope[CloneOut], status_code=201)
async def clone_request(request_id: int, session: DbSession):
    return Envelope(data=await replay_service.clone_request(session, request_id))


@router.post("/requests/{request_id}/replay", response_model=Envelope[ReplayRecordOut])
async def replay_request(request_id: int, payload: ReplayCreate, request: Request):
    service = request.app.state.replay_service
    record = await service.execute(request_id, payload)
    return Envelope(data=ReplayRecordOut.model_validate(record))


@router.get("/requests/{request_id}/replays", response_model=Envelope[list[ReplayRecordOut]])
async def list_replays(request_id: int, session: DbSession):
    await request_service.get_request_detail(session, request_id)  # 404 when unknown
    records = await replay_service.list_replays(session, request_id)
    return Envelope(data=[ReplayRecordOut.model_validate(r) for r in records])
