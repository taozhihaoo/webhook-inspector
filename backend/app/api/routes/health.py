"""Health check (unauthenticated; used by docker healthcheck)."""

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.api.deps import DbSession
from app.config import Settings
from app.schemas import Envelope, HealthOut

router = APIRouter()


@router.get("/health", response_model=Envelope[HealthOut])
async def health(request: Request, session: DbSession):
    await session.execute(text("SELECT 1"))
    settings: Settings = request.app.state.settings
    return Envelope(data=HealthOut(status="ok", version=settings.version, database="ok"))
