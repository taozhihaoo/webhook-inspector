"""Alembic migration integrity: upgrade creates the full schema from scratch."""

import sqlite3

from alembic import command
from alembic.config import Config

EXPECTED_TABLES = {"webhook_endpoints", "webhook_requests", "replay_records", "alembic_version"}


def _columns(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_migration_creates_full_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "migration-test.db"
    url = f"sqlite+aiosqlite:///{db_path}"

    monkeypatch.setenv("DATABASE_URL", url)
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    finally:
        get_settings.cache_clear()
        monkeypatch.undo()

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert tables >= EXPECTED_TABLES

    assert "public_id" in _columns(db_path, "webhook_endpoints")
    assert "signature_secret_encrypted" in _columns(db_path, "webhook_endpoints")
    assert "body_raw" in _columns(db_path, "webhook_requests")
    assert "signature_status" in _columns(db_path, "webhook_requests")
    assert "response_body_preview" in _columns(db_path, "replay_records")


def test_migration_downgrade_removes_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "migration-down.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        command.downgrade(config, "base")
    finally:
        get_settings.cache_clear()
        monkeypatch.undo()

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    # alembic_version intentionally survives downgrade; domain tables must go.
    assert not ({"webhook_endpoints", "webhook_requests", "replay_records"} & tables)
