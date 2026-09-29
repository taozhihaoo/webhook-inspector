"""Database models: webhook endpoints, captured requests, replay records."""

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db_base import Base

# JSON on SQLite, JSONB on PostgreSQL.
JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class SignatureStatus(enum.StrEnum):
    verified = "verified"
    invalid = "invalid"
    not_configured = "not_configured"
    error = "error"


class IngestAuthStatus(enum.StrEnum):
    not_configured = "not_configured"
    valid = "valid"
    invalid = "invalid"


class ReplayStatus(enum.StrEnum):
    success = "success"
    error = "error"
    blocked = "blocked"
    timeout = "timeout"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class WebhookEndpoint(TimestampMixin, Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    max_requests: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    request_retention_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Static response returned to webhook senders.
    response_status: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    response_content_type: Mapped[str] = mapped_column(
        String(200), default="application/json", nullable=False
    )
    response_body: Mapped[str] = mapped_column(Text, default='{"received": true}', nullable=False)
    response_delay_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    replay_target_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # Signature verification (generic HMAC).
    signature_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    signature_header: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signature_algorithm: Mapped[str | None] = mapped_column(String(50), nullable=True)
    signature_encoding: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Encrypted at rest; never returned by the API.
    signature_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional shared token webhook senders must present (X-Webhook-Token); stored as SHA-256.
    ingest_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    requests: Mapped[list["WebhookRequest"]] = relationship(
        back_populates="endpoint",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WebhookRequest.id.desc()",
    )


class WebhookRequest(TimestampMixin, Base):
    __tablename__ = "webhook_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    endpoint_id: Mapped[int] = mapped_column(
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), index=True, nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )

    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    query_parameters: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    headers: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)

    body_raw: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # Lossy UTF-8 decode used for display and search; body_raw stays untouched.
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_json: Mapped[dict | list | None] = mapped_column(JSONVariant, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    body_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Direct peer address (or proxy header when trust_proxy_headers is enabled).
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    processing_duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    signature_status: Mapped[SignatureStatus] = mapped_column(
        Enum(SignatureStatus, native_enum=False, length=20, validate_strings=True),
        default=SignatureStatus.not_configured,
        nullable=False,
    )
    ingest_auth_status: Mapped[IngestAuthStatus] = mapped_column(
        Enum(IngestAuthStatus, native_enum=False, length=20, validate_strings=True),
        default=IngestAuthStatus.not_configured,
        nullable=False,
    )
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    replayable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    endpoint: Mapped[WebhookEndpoint] = relationship(back_populates="requests")
    replays: Mapped[list["ReplayRecord"]] = relationship(
        back_populates="original_request", cascade="all, delete-orphan", passive_deletes=True
    )


class ReplayRecord(TimestampMixin, Base):
    __tablename__ = "replay_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    original_request_id: Mapped[int] = mapped_column(
        ForeignKey("webhook_requests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    target_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    headers: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    body: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    status: Mapped[ReplayStatus] = mapped_column(
        Enum(ReplayStatus, native_enum=False, length=20, validate_strings=True), nullable=False
    )
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_headers: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    response_body_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    original_request: Mapped[WebhookRequest] = relationship(back_populates="replays")
