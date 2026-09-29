"""Initial schema: webhook_endpoints, webhook_requests, replay_records.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _enum(values, name):
    return sa.Enum(*values, name=name, native_enum=False, length=20, validate_strings=True)


def upgrade() -> None:
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("max_requests", sa.Integer(), server_default="1000", nullable=False),
        sa.Column("request_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("request_retention_hours", sa.Integer(), nullable=True),
        sa.Column("response_status", sa.Integer(), server_default="200", nullable=False),
        sa.Column(
            "response_content_type",
            sa.String(length=200),
            server_default="application/json",
            nullable=False,
        ),
        sa.Column(
            "response_body", sa.Text(), server_default='{"received": true}', nullable=False
        ),
        sa.Column("response_delay_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("replay_target_url", sa.String(length=2000), nullable=True),
        sa.Column("signature_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("signature_header", sa.String(length=200), nullable=True),
        sa.Column("signature_algorithm", sa.String(length=50), nullable=True),
        sa.Column("signature_encoding", sa.String(length=20), nullable=True),
        sa.Column("signature_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("ingest_token_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index(
        "ix_webhook_endpoints_public_id", "webhook_endpoints", ["public_id"], unique=True
    )
    op.create_index("ix_webhook_endpoints_expires_at", "webhook_endpoints", ["expires_at"])

    op.create_table(
        "webhook_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("endpoint_id", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=1000), nullable=False),
        sa.Column("query_parameters", sa.JSON(), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("body_raw", sa.LargeBinary(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_json", sa.JSON(), nullable=True),
        sa.Column("content_type", sa.String(length=200), nullable=True),
        sa.Column("body_size", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("processing_duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "signature_status",
            _enum(["verified", "invalid", "not_configured", "error"], "signaturestatus"),
            server_default="not_configured",
            nullable=False,
        ),
        sa.Column(
            "ingest_auth_status",
            _enum(["not_configured", "valid", "invalid"], "ingestauthstatus"),
            server_default="not_configured",
            nullable=False,
        ),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("replayable", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id"], ["webhook_endpoints.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhook_requests_endpoint_id", "webhook_requests", ["endpoint_id"])
    op.create_index("ix_webhook_requests_received_at", "webhook_requests", ["received_at"])

    op.create_table(
        "replay_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("original_request_id", sa.Integer(), nullable=False),
        sa.Column("target_url", sa.String(length=2000), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=True),
        sa.Column(
            "status",
            _enum(["success", "error", "blocked", "timeout"], "replaystatus"),
            nullable=False,
        ),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_headers", sa.JSON(), nullable=True),
        sa.Column("response_body_preview", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["original_request_id"], ["webhook_requests.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_replay_records_original_request_id", "replay_records", ["original_request_id"]
    )


def downgrade() -> None:
    op.drop_table("replay_records")
    op.drop_table("webhook_requests")
    op.drop_table("webhook_endpoints")
