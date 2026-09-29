"""Shared FastAPI dependencies."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import Unauthorized
from app.services import crypto


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def require_admin(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Bearer-token guard for the management API."""
    if not authorization or not authorization.startswith("Bearer "):
        raise Unauthorized()
    provided = authorization.removeprefix("Bearer ").strip()
    expected = request.app.state.settings.admin_api_token
    if not provided or not crypto.secrets_equal(provided, expected):
        raise Unauthorized()
