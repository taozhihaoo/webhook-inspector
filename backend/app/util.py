"""Small shared helpers."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime; SQLite may hand back naive values."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def decode_lossy(data: bytes | None) -> str | None:
    """Best-effort UTF-8 decode used for display/search (raw bytes stay untouched).

    NUL bytes are replaced: PostgreSQL TEXT columns reject them, and they have
    no display value anyway.
    """
    if data is None:
        return None
    return data.decode("utf-8", errors="replace").replace("\x00", "\ufffd")
