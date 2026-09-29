"""Alembic environment (async engine)."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from app import models  # noqa: F401  (registers models on Base.metadata)
from app.config import get_settings
from app.db_base import Base
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _settings():
    # Migrations do not use the secrets, but Settings requires them to be set.
    os.environ.setdefault("ADMIN_API_TOKEN", "migration-placeholder")
    os.environ.setdefault("SECRET_KEY", "migration-placeholder")
    return get_settings()


def run_migrations_offline() -> None:
    context.configure(
        url=_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _settings().database_url
    connectable = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
