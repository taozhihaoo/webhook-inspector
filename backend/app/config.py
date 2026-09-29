"""Application settings loaded from environment variables / .env file."""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that are acceptable while developing but must never reach production.
_WEAK_SECRET_VALUES = frozenset(
    {
        "change-me-admin-token",
        "change-me-secret-key",
        "changeme",
        "dev-admin-token-change-me",
        "dev-secret-key-change-me-0123456789abcdef",
        "test-admin-token",
        "test-secret-key-for-unit-tests",
        "ci-placeholder-token",
        "ci-placeholder-secret",
        "e2e-admin-token",
        "e2e-secret-key-for-ci",
        "migration-placeholder",
        "admin",
        "secret",
        "password",
    }
)
_MIN_SECRET_LENGTH = 16


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"  # development | test | production
    version: str = "0.2.0"

    # --- Required secrets (fail fast if missing; never log or return them) ---
    admin_api_token: str
    secret_key: str  # used to encrypt per-endpoint signature secrets at rest

    # --- Database ---
    database_url: str = "postgresql+asyncpg://webhook:webhook@localhost:5432/webhook_inspector"

    # --- Public URL building (empty = derive from the incoming request) ---
    base_url: str = ""

    # --- HTTP / CORS ---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    trust_proxy_headers: bool = False  # only enable behind a trusted reverse proxy

    # --- Ingestion limits ---
    max_body_size: int = 1_000_000  # bytes; larger requests get 413

    # --- Replay ---
    allow_http_replay: bool = False  # default: replay targets must be https://
    replay_allow_private_networks: bool = False  # dev/demo escape hatch; keep off in production
    replay_timeout_seconds: float = 10.0
    replay_max_redirects: int = 3
    replay_max_response_bytes: int = 65_536

    # --- Rate limiting (single-instance, in-process) ---
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60

    # --- Cleanup worker ---
    cleanup_interval_seconds: int = 60
    cleanup_grace_hours: int = 24  # expired endpoints are deleted this long after expiry

    # --- Dev/demo helpers ---
    enable_mock_receiver: bool = True

    @model_validator(mode="after")
    def _reject_weak_production_secrets(self):
        """Refuse to boot production with default/weak or short secrets."""
        if self.app_env != "production":
            return self
        problems = []
        for name, value in (
            ("ADMIN_API_TOKEN", self.admin_api_token),
            ("SECRET_KEY", self.secret_key),
        ):
            if value in _WEAK_SECRET_VALUES or len(value) < _MIN_SECRET_LENGTH:
                problems.append(name)
        if not problems and self.admin_api_token == self.secret_key:
            problems.append("ADMIN_API_TOKEN and SECRET_KEY (identical values)")
        if problems:
            raise ValueError(
                f"Refusing to start in production with weak/default secrets: "
                f"{', '.join(problems)}. Provide strong random values "
                f"(>= {_MIN_SECRET_LENGTH} chars, not from the documented defaults)."
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from env
