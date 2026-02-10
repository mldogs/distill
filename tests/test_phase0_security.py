"""Phase 0 (security hardening) tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.config import Settings


def _set_min_prod_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ENABLE_DEV_LOGIN", "false")
    monkeypatch.setenv("CORS_ORIGINS", "http://example.com")
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "true")


def test_admin_ids_all_rejected_in_prod(monkeypatch: pytest.MonkeyPatch):
    _set_min_prod_env(monkeypatch)
    monkeypatch.setenv("ADMIN_IDS", "all")
    monkeypatch.setenv("JWT_SECRET", "x" * 64)

    with pytest.raises(ValidationError, match=r"ADMIN_IDS"):
        Settings()


def test_jwt_secret_blank_rejected_in_prod(monkeypatch: pytest.MonkeyPatch):
    _set_min_prod_env(monkeypatch)
    monkeypatch.setenv("ADMIN_IDS", "123")
    monkeypatch.setenv("JWT_SECRET", "")

    with pytest.raises(ValidationError, match=r"JWT_SECRET"):
        Settings()


def test_jwt_secret_placeholder_rejected_in_prod(monkeypatch: pytest.MonkeyPatch):
    _set_min_prod_env(monkeypatch)
    monkeypatch.setenv("ADMIN_IDS", "123")
    monkeypatch.setenv("JWT_SECRET", "change-me-in-production")

    with pytest.raises(ValidationError, match=r"JWT_SECRET"):
        Settings()


def test_cors_wildcard_forces_no_credentials(monkeypatch: pytest.MonkeyPatch):
    _set_min_prod_env(monkeypatch)
    monkeypatch.setenv("ADMIN_IDS", "123")
    monkeypatch.setenv("JWT_SECRET", "x" * 64)
    monkeypatch.setenv("CORS_ORIGINS", "*")
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "true")

    settings = Settings()
    assert settings.cors_origins_list == ["*"]
    assert settings.cors_allow_credentials is False


def test_admin_ids_match_numeric_provider_id(monkeypatch: pytest.MonkeyPatch):
    _set_min_prod_env(monkeypatch)
    monkeypatch.setenv("ADMIN_IDS", "166898548")
    monkeypatch.setenv("JWT_SECRET", "x" * 64)

    settings = Settings()
    assert settings.is_admin_user(1, provider="telegram", provider_id="166898548") is True
    assert settings.is_admin_user(1, provider="telegram", provider_id="1") is False
