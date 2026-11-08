"""Alembic environment (async).

Settings come from ``config.attributes["settings"]`` when a caller (such as a
test) injects them; otherwise they are loaded from the environment, which fails
with a list of every missing key.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from core.config import ConfigError, Settings, load_settings
from core.models import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _settings() -> Settings:
    injected = config.attributes.get("settings")
    if isinstance(injected, Settings):
        return injected
    try:
        settings = load_settings()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from None
    config.attributes["settings"] = settings
    return settings


def run_migrations_offline() -> None:
    context.configure(
        url=_settings().DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine = create_async_engine(_settings().DATABASE_URL)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
