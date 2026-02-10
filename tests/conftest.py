"""Shared pytest fixtures for tests."""
from __future__ import annotations

import os
import uuid

# CRITICAL: set test env vars BEFORE any project imports.
# storage/config.py calls load_dotenv() at import time — if DB_SCHEMA
# is not yet in os.environ, tests could write to the production database.
os.environ.setdefault("TG_STOCK_TESTING", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_DEV_LOGIN", "true")
if "DB_SCHEMA" not in os.environ:
    os.environ["DB_SCHEMA"] = f"tg_stock_test_{uuid.uuid4().hex[:8]}"
os.environ.setdefault("DB_POOL_SIZE", "5")
os.environ.setdefault("DB_MAX_OVERFLOW", "5")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from storage import reset_database


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def test_db_schema():
    """Create an isolated schema for the whole test session, then drop it."""
    from sqlalchemy import text
    from storage import Database

    schema = os.environ["DB_SCHEMA"]
    if not schema.startswith("tg_stock_test_"):
        raise RuntimeError(
            f"Refusing to run tests with DB_SCHEMA={schema!r}. "
            "Unset DB_SCHEMA or set it to a tg_stock_test_* value."
        )
    db = Database()
    try:
        # Ensure schema exists (engine already sets search_path to it).
        async with db.engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        # Create all tables inside the schema.
        await db.create_tables()

        yield
    finally:
        # Drop schema and everything inside it so tests leave no traces.
        async with db.engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await db.close()


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset all async singletons before each test to avoid event loop conflicts."""
    from api.config import reset_settings
    from core.settings import reset_settings_manager
    from ranker.locking import reset_ranking_lock

    reset_database()
    reset_settings()
    reset_settings_manager()
    reset_ranking_lock()
    yield
    reset_database()
    reset_settings()
    reset_settings_manager()
    reset_ranking_lock()


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for API tests."""
    # Import app after reset to ensure fresh database
    from api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient):
    """Authenticated HTTP client with JWT token."""
    # Get token via dev-login
    response = await client.post("/auth/dev-login?username=test_api_user")
    data = response.json()
    token = data["access_token"]

    # Return client with auth header helper
    class AuthClient:
        def __init__(self, client: AsyncClient, token: str):
            self._client = client
            self._token = token
            self._headers = {"Authorization": f"Bearer {token}"}

        @property
        def token(self) -> str:
            return self._token

        @property
        def headers(self) -> dict:
            return self._headers

        async def get(self, url: str, **kwargs):
            kwargs.setdefault("headers", {}).update(self._headers)
            return await self._client.get(url, **kwargs)

        async def post(self, url: str, **kwargs):
            kwargs.setdefault("headers", {}).update(self._headers)
            return await self._client.post(url, **kwargs)

        async def put(self, url: str, **kwargs):
            kwargs.setdefault("headers", {}).update(self._headers)
            return await self._client.put(url, **kwargs)

        async def patch(self, url: str, **kwargs):
            kwargs.setdefault("headers", {}).update(self._headers)
            return await self._client.patch(url, **kwargs)

        async def delete(self, url: str, **kwargs):
            kwargs.setdefault("headers", {}).update(self._headers)
            return await self._client.delete(url, **kwargs)

    return AuthClient(client, token)


@pytest_asyncio.fixture
async def admin_client(auth_client):
    """Authenticated HTTP client with admin privileges.

    Note: This assumes ADMIN_IDS is set to 'all' in test environment,
    which is the default for development mode.
    """
    # In test mode, ADMIN_IDS should be 'all' or include test user ID
    return auth_client
