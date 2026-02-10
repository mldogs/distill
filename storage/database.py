"""Async database engine and session management."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from storage.config import DatabaseConfig
from storage.models import Base


class Database:
    """Async database connection manager."""

    def __init__(self, config: Optional[DatabaseConfig] = None):
        """Initialize database with configuration."""
        self.config = config or DatabaseConfig.from_env()

        # Safety: refuse to touch production DB when running under pytest.
        if os.environ.get("TG_STOCK_TESTING") and (
            not self.config.schema
            or not self.config.schema.startswith("tg_stock_test_")
        ):
            raise RuntimeError(
                f"Test mode active (TG_STOCK_TESTING=1) but DB_SCHEMA="
                f"{self.config.schema!r} is not a test schema. "
                f"This guard prevents tests from writing to production."
            )
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None

    @property
    def engine(self) -> AsyncEngine:
        """Get or create async engine."""
        if self._engine is None:
            engine_kwargs: dict = {
                "echo": False,
                "pool_pre_ping": True,
                "pool_size": self.config.pool_size,
                "max_overflow": self.config.max_overflow,
            }

            # Optional schema isolation (used by tests). For asyncpg, server_settings controls search_path.
            if self.config.schema:
                engine_kwargs["connect_args"] = {"server_settings": {"search_path": f"{self.config.schema},public"}}

            self._engine = create_async_engine(self.config.async_url, **engine_kwargs)
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Get or create session factory."""
        if self._session_factory is None:
            self._session_factory = async_sessionmaker(
                bind=self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
        return self._session_factory

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Provide a transactional scope around a series of operations."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def create_tables(self) -> None:
        """Create all tables (for testing/development)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_tables(self) -> None:
        """Drop all tables (for testing)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def close(self) -> None:
        """Close engine and release connections."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None


_db: Optional[Database] = None


def get_database() -> Database:
    """Get global database instance."""
    global _db
    if _db is None:
        _db = Database()
    return _db


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI - yields a database session."""
    db = get_database()
    async with db.session() as session:
        yield session


def reset_database() -> None:
    """Reset global database instance (for testing)."""
    global _db
    _db = None
