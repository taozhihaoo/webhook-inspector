"""Pydantic schemas for the management API."""

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

Algorithm = Literal["hmac-sha256", "hmac-sha1", "hmac-sha384", "hmac-sha512"]
SignatureEncoding = Literal["hex", "base64"]

RESPONSE_BODY_MAX = 65_536


# --------------------------------------------------------------------------- #
# Envelope
# --------------------------------------------------------------------------- #

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    """Uniform success envelope: {"data": ...}."""

    data: T


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


class SignatureConfig(BaseModel):
    enabled: bool = True
    header: str = Field(default="X-Signature", min_length=1, max_length=200)
    algorithm: Algorithm = "hmac-sha256"
    encoding: SignatureEncoding = "hex"
    # Required when enabling/rotating; omitted on update keeps the stored secret.
    secret: SecretStr | None = Field(default=None, min_length=1, max_length=1000)


class EndpointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    ttl_hours: int = Field(default=24, ge=1, le=87_600)
    max_requests: int = Field(default=1000, ge=1, le=1_000_000)
    request_retention_hours: int | None = Field(default=None, ge=1, le=87_600)

    response_status: int = Field(default=200, ge=100, le=599)
    response_body: str = Field(default='{"received": true}', max_length=RESPONSE_BODY_MAX)
    response_content_type: str = Field(default="application/json", max_length=200)
    response_delay_ms: int = Field(default=0, ge=0, le=10_000)

    replay_target_url: str | None = Field(default=None, max_length=2000)
    signature: SignatureConfig | None = None
    ingest_token: SecretStr | None = Field(default=None, min_length=1, max_length=1000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class EndpointUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    # Provide to extend/shorten expiry relative to *now*.
    ttl_hours: int | None = Field(default=None, ge=1, le=87_600)
    max_requests: int | None = Field(default=None, ge=1, le=1_000_000)
    request_retention_hours: int | None = Field(default=None, ge=1, le=87_600)

    response_status: int | None = Field(default=None, ge=100, le=599)
    response_body: str | None = Field(default=None, max_length=RESPONSE_BODY_MAX)
    response_content_type: str | None = Field(default=None, max_length=200)
    response_delay_ms: int | None = Field(default=None, ge=0, le=10_000)

    replay_target_url: str | None = Field(default=None, max_length=2000)
    signature: SignatureConfig | None = None
    # Token to set/rotate; send "remove_ingest_token": true to clear it
    # (a bare null means "no change", because the field is unset vs null).
    ingest_token: SecretStr | None = Field(default=None, min_length=1, max_length=1000)
    remove_ingest_token: bool = False


class SignatureStatusInfo(BaseModel):
    enabled: bool
    header: str | None
    algorithm: str | None
    encoding: str | None
    configured: bool  # secret present


class EndpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    public_id: str
    webhook_url: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    enabled: bool
    max_requests: int
    request_count: int
    request_retention_hours: int | None
    status: Literal["active", "expired", "disabled"]
    last_request_at: datetime | None

    response_status: int
    response_content_type: str
    response_body: str
    response_delay_ms: int

    replay_target_url: str | None
    signature: SignatureStatusInfo
    ingest_token_configured: bool


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


class RequestSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    endpoint_id: int
    received_at: datetime
    method: str
    path: str
    content_type: str | None
    body_size: int
    signature_status: str
    ingest_auth_status: str
    response_status: int


class RequestDetail(RequestSummary):
    query_parameters: dict[str, str]
    headers: dict[str, str]
    body_text: str | None
    body_json: object | None
    source_ip: str | None
    processing_duration_ms: int
    replayable: bool


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #


class ReplayCreate(BaseModel):
    # Defaults come from the endpoint configuration / original request.
    target_url: str | None = Field(default=None, max_length=2000)
    method: str | None = Field(default=None, min_length=1, max_length=10)
    headers: dict[str, str] | None = None
    # When omitted, the stored original body bytes are replayed unchanged.
    body_text: str | None = Field(default=None, max_length=2_000_000)


class ReplayRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_request_id: int
    target_url: str
    method: str
    headers: dict[str, str]
    status: str
    response_status: int | None
    response_headers: dict[str, str] | None
    response_body_preview: str | None
    duration_ms: int | None
    error_message: str | None
    created_at: datetime


class CloneOut(BaseModel):
    target_url: str | None
    method: str
    headers: dict[str, str]
    body_text: str | None
    content_type: str | None
    query_parameters: dict[str, str]


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #


class HealthOut(BaseModel):
    status: Literal["ok"]
    version: str
    database: Literal["ok"]


class DeleteOut(BaseModel):
    deleted: bool
    count: int | None = None
