"""Tests for API endpoints."""
from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from httpx import AsyncClient


class TestHealth:
    """Tests for health endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client: AsyncClient):
        """Test GET /health returns status ok."""
        response = await client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestStats:
    """Tests for stats endpoint."""

    @pytest.mark.asyncio
    async def test_stats_returns_counts(self, client: AsyncClient):
        """Test GET /stats returns all counts."""
        response = await client.get("/stats")

        assert response.status_code == 200
        data = response.json()

        # Check all expected fields
        assert "channels_count" in data
        assert "posts_count" in data
        assert "scores_count" in data
        assert "votes_count" in data
        assert "users_count" in data

        # All should be non-negative numbers (avg_score is float)
        assert all(isinstance(v, (int, float)) and v >= 0 for v in data.values())


class TestFeed:
    """Tests for feed endpoint."""

    @pytest.mark.asyncio
    async def test_feed_default_params(self, client: AsyncClient):
        """Test GET /feed with default parameters."""
        response = await client.get("/feed")

        assert response.status_code == 200
        data = response.json()

        assert "posts" in data
        assert "total" in data
        assert "period" in data
        assert "formula" in data
        assert isinstance(data["posts"], list)

    @pytest.mark.asyncio
    async def test_feed_with_limit(self, client: AsyncClient):
        """Test GET /feed respects limit parameter."""
        response = await client.get("/feed?limit=2")

        assert response.status_code == 200
        data = response.json()

        assert len(data["posts"]) <= 2

    @pytest.mark.asyncio
    async def test_feed_with_period(self, client: AsyncClient):
        """Test GET /feed with different periods."""
        for period in ["24h", "daily", "weekly", "monthly"]:
            response = await client.get(f"/feed?period={period}")

            assert response.status_code == 200
            data = response.json()
            assert data["period"] == period

    @pytest.mark.asyncio
    async def test_feed_with_formula(self, client: AsyncClient):
        """Test GET /feed with different formulas."""
        for formula in ["v2", "v4"]:
            response = await client.get(f"/feed?formula={formula}")

            assert response.status_code == 200
            data = response.json()
            assert data["formula"] == formula

    @pytest.mark.asyncio
    async def test_feed_post_structure(self, client: AsyncClient):
        """Test feed posts have correct structure."""
        response = await client.get("/feed?limit=1")

        assert response.status_code == 200
        data = response.json()

        if data["posts"]:
            post = data["posts"][0]

            # Required fields
            assert "id" in post
            assert "permalink" in post
            assert "posted_at" in post
            assert "score" in post
            assert "channel" in post

            # Channel structure
            assert "id" in post["channel"]
            assert "username" in post["channel"]

    @pytest.mark.asyncio
    async def test_feed_invalid_limit(self, client: AsyncClient):
        """Test GET /feed rejects invalid limit."""
        response = await client.get("/feed?limit=0")
        assert response.status_code == 422  # Validation error

        response = await client.get("/feed?limit=200")
        assert response.status_code == 422  # Exceeds max


class TestAuth:
    """Tests for authentication endpoints."""

    @pytest.mark.asyncio
    async def test_dev_login_creates_user(self, client: AsyncClient):
        """Test POST /auth/dev-login creates user and returns token."""
        response = await client.post("/auth/dev-login?username=new_test_user")

        assert response.status_code == 200
        data = response.json()

        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "user" in data
        assert data["user"]["username"] == "new_test_user"
        assert data["user"]["provider"] == "dev"

    @pytest.mark.asyncio
    async def test_dev_login_default_username(self, client: AsyncClient):
        """Test POST /auth/dev-login uses default username."""
        response = await client.post("/auth/dev-login")

        assert response.status_code == 200
        data = response.json()
        assert data["user"]["username"] == "test_user"

    @pytest.mark.asyncio
    async def test_auth_me_with_token(self, auth_client):
        """Test GET /auth/me returns current user."""
        response = await auth_client.get("/auth/me")

        assert response.status_code == 200
        data = response.json()

        assert "id" in data
        assert "provider" in data
        assert "username" in data

    @pytest.mark.asyncio
    async def test_auth_me_without_token(self, client: AsyncClient):
        """Test GET /auth/me requires authentication."""
        response = await client.get("/auth/me")

        assert response.status_code == 401
        assert response.json()["detail"] == "Not authenticated"

    @pytest.mark.asyncio
    async def test_auth_me_invalid_token(self, client: AsyncClient):
        """Test GET /auth/me rejects invalid token."""
        response = await client.get(
            "/auth/me",
            headers={"Authorization": "Bearer invalid_token"},
        )

        assert response.status_code == 401
        assert "Invalid" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_telegram_auth_invalid_hash(self, client: AsyncClient):
        """Test POST /auth/telegram rejects invalid hash."""
        response = await client.post(
            "/auth/telegram",
            json={
                "id": 123456789,
                "first_name": "Test",
                "auth_date": 1704067200,
                "hash": "invalid_hash",
            },
        )

        assert response.status_code == 401
        assert "Invalid Telegram" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_dev_login_disabled_in_prod(self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
        """In prod, /auth/dev-login should not be usable."""
        from api.config import reset_settings

        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.setenv("ENABLE_DEV_LOGIN", "false")
        monkeypatch.setenv("JWT_SECRET", "x" * 64)
        monkeypatch.setenv("ADMIN_IDS", "123")
        monkeypatch.setenv("CORS_ORIGINS", "http://example.com")
        reset_settings()

        response = await client.post("/auth/dev-login")
        assert response.status_code == 404

    def _make_valid_telegram_auth(self, bot_token: str, auth_date: int) -> dict:
        data = {
            "id": 123456789,
            "first_name": "Test",
            "last_name": "User",
            "username": "testuser",
            "photo_url": "https://t.me/i/userpic/123.jpg",
            "auth_date": auth_date,
        }

        check_arr = []
        for key, value in sorted(data.items()):
            if value is not None:
                check_arr.append(f"{key}={value}")
        data_check_string = "\n".join(check_arr)

        secret_key = hashlib.sha256(bot_token.encode()).digest()
        data["hash"] = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()
        return data

    @pytest.mark.asyncio
    async def test_telegram_auth_date_too_old(self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
        """Old auth_date should be rejected (anti-replay)."""
        from api.config import reset_settings

        bot_token = "123456:TEST_TOKEN"
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)
        monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "60")
        reset_settings()

        payload = self._make_valid_telegram_auth(
            bot_token=bot_token,
            auth_date=int(time.time()) - 3600,
        )

        response = await client.post("/auth/telegram", json=payload)
        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_telegram_auth_date_valid(self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
        """Fresh auth_date should be accepted."""
        from api.config import reset_settings

        bot_token = "123456:TEST_TOKEN"
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)
        monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "60")
        reset_settings()

        payload = self._make_valid_telegram_auth(
            bot_token=bot_token,
            auth_date=int(time.time()),
        )

        response = await client.post("/auth/telegram", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["user"]["provider"] == "telegram"


class TestVote:
    """Tests for voting endpoint."""

    @pytest.mark.asyncio
    async def test_vote_requires_auth(self, client: AsyncClient):
        """Test POST /vote requires authentication."""
        response = await client.post(
            "/vote",
            json={"post_id": 1, "value": 1},
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_vote_invalid_post(self, auth_client):
        """Test POST /vote with non-existent post."""
        response = await auth_client.post(
            "/vote",
            json={"post_id": 999999999, "value": 1},
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_vote_invalid_value(self, auth_client):
        """Test POST /vote rejects invalid vote values."""
        response = await auth_client.post(
            "/vote",
            json={"post_id": 1, "value": 5},
        )

        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_vote_stats_invalid_post(self, client: AsyncClient):
        """Test GET /vote/{post_id} with non-existent post."""
        response = await client.get("/vote/999999999")

        assert response.status_code == 404


class TestSummary:
    """Tests for summary endpoint."""

    @pytest.mark.asyncio
    async def test_summary_not_found(self, client: AsyncClient):
        """Test GET /summary returns 404 when no summary exists."""
        # Use a period type that definitely has no summary
        response = await client.get("/summary?period=nonexistent_period_xyz")

        assert response.status_code == 404


class TestOpenAPI:
    """Tests for OpenAPI documentation."""

    @pytest.mark.asyncio
    async def test_openapi_schema_available(self, client: AsyncClient):
        """Test OpenAPI schema is available."""
        response = await client.get("/openapi.json")

        assert response.status_code == 200
        data = response.json()

        assert "openapi" in data
        assert "paths" in data
        assert "/health" in data["paths"]
        assert "/feed" in data["paths"]
        assert "/vote" in data["paths"]

    @pytest.mark.asyncio
    async def test_swagger_ui_available(self, client: AsyncClient):
        """Test Swagger UI is available."""
        response = await client.get("/docs")

        assert response.status_code == 200
        assert "swagger" in response.text.lower()


class TestAdminSettings:
    """Tests for admin settings endpoints."""

    @pytest.mark.asyncio
    async def test_settings_accepts_collector_knobs(self, admin_client):
        """Test PUT /admin/settings accepts new collector settings."""
        response = await admin_client.put(
            "/admin/settings",
            json={
                "settings": {
                    "collector.incremental_grace_minutes": 20,
                    "collector.refresh_recent_hours": 12,
                }
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert "collector.incremental_grace_minutes" in data["updated"]
        assert "collector.refresh_recent_hours" in data["updated"]
        assert data["settings"]["collector.incremental_grace_minutes"] == 20
        assert data["settings"]["collector.refresh_recent_hours"] == 12

    @pytest.mark.asyncio
    async def test_settings_validates_collector_ranges(self, admin_client):
        """Test PUT /admin/settings validates collector setting ranges."""
        # Test grace_minutes out of range
        response = await admin_client.put(
            "/admin/settings",
            json={
                "settings": {
                    "collector.incremental_grace_minutes": 200,  # max is 180
                }
            },
        )

        assert response.status_code == 400
        assert "maximum is 180" in str(response.json()["detail"])

        # Test refresh_hours out of range
        response = await admin_client.put(
            "/admin/settings",
            json={
                "settings": {
                    "collector.refresh_recent_hours": 200,  # max is 168
                }
            },
        )

        assert response.status_code == 400
        assert "maximum is 168" in str(response.json()["detail"])
