"""Application factory."""

import asyncio
import logging
from collections import deque
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.deps import require_admin
from app.api.routes import endpoints, events, health, hook, mock, requests
from app.config import Settings, get_settings
from app.db import create_engine, make_session_factory
from app.errors import AppError
from app.services.cleanup_service import CleanupService
from app.services.events import EventBroker
from app.services.rate_limit import SlidingWindowRateLimiter
from app.services.replay_service import ReplayService

logger = logging.getLogger("webhook_inspector")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# Path segments that must never fall through to the SPA catch-all.
RESERVED_SEGMENTS = {"api", "hook", "mock", "docs", "redoc", "openapi.json", "assets"}

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup = CleanupService(app.state.session_factory, app.state.settings)
    task = asyncio.create_task(cleanup.run_forever(), name="cleanup-worker")
    logger.info("Webhook Inspector %s started", app.state.settings.version)
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    await app.state.engine.dispose()
    logger.info("Webhook Inspector stopped")


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}},
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        if errors:
            parts = []
            for error in errors[:5]:
                loc = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
                parts.append(f"{loc}: {error.get('msg', 'validation failed')}")
            message = f"Invalid input ({'; '.join(parts)})"
        else:
            message = "Invalid input."
        return JSONResponse(
            {"error": {"code": "invalid_input", "message": message}}, status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(
            {"error": {"code": code, "message": str(exc.detail)}},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "Internal server error."}},
            status_code=500,
        )


def mount_spa(app: FastAPI) -> None:
    """Serve the built frontend (single origin: no CORS in production)."""
    if not (STATIC_DIR / "index.html").exists():
        return
    assets = STATIC_DIR / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{spa_path:path}", include_in_schema=False, response_model=None)
    async def spa(spa_path: str) -> FileResponse | JSONResponse:
        if spa_path.split("/", 1)[0] in RESERVED_SEGMENTS:
            return JSONResponse(
                {"error": {"code": "not_found", "message": "Resource not found."}}, status_code=404
            )
        candidate = (STATIC_DIR / spa_path).resolve()
        if spa_path and candidate.is_file() and candidate.is_relative_to(STATIC_DIR):
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="Webhook Inspector",
        version=__version__,
        description="Capture, inspect, search, replay and test HTTP webhooks.",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = create_engine(settings)
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.broker = EventBroker()
    app.state.rate_limiter = SlidingWindowRateLimiter(
        settings.rate_limit_requests, settings.rate_limit_window_seconds
    )
    app.state.replay_service = ReplayService(app.state.session_factory, settings)
    app.state.mock_history = deque(maxlen=100)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,  # bearer-token auth: no cookies involved
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "Retry-After",
        ],
    )

    health_router = APIRouter(prefix="/api")
    health_router.include_router(health.router)
    app.include_router(health_router)

    api_router = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])
    api_router.include_router(endpoints.router)
    api_router.include_router(requests.router)
    api_router.include_router(events.router)
    app.include_router(api_router)

    app.include_router(hook.router)
    if settings.enable_mock_receiver:
        app.include_router(mock.router)

    install_exception_handlers(app)
    mount_spa(app)
    return app


app = create_app()
