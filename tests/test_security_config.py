"""Tests for security-sensitive configuration defaults/validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.config import Settings


def test_dev_generates_jwt_secret_when_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("ADMIN_IDS", raising=False)
    monkeypatch.delenv("ENABLE_DEV_LOGIN", raising=False)

    s = Settings(_env_file=None)
    assert s.jwt_secret
    assert isinstance(s.jwt_secret, str)
    assert len(s.jwt_secret) >= 32


def test_prod_rejects_blank_jwt_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ADMIN_IDS", "123")
    monkeypatch.setenv("JWT_SECRET", "")
    monkeypatch.setenv("ENABLE_DEV_LOGIN", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_prod_rejects_placeholder_jwt_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ADMIN_IDS", "123")
    monkeypatch.setenv("JWT_SECRET", "change-me-in-production")
    monkeypatch.setenv("ENABLE_DEV_LOGIN", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_prod_rejects_admin_ids_all(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ADMIN_IDS", "all")
    monkeypatch.setenv("JWT_SECRET", "a" * 64)
    monkeypatch.setenv("ENABLE_DEV_LOGIN", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_prod_rejects_enable_dev_login(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ADMIN_IDS", "123")
    monkeypatch.setenv("JWT_SECRET", "a" * 64)
    monkeypatch.setenv("ENABLE_DEV_LOGIN", "1")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_prod_rejects_cors_star_with_credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ADMIN_IDS", "123")
    monkeypatch.setenv("JWT_SECRET", "a" * 64)
    monkeypatch.setenv("CORS_ORIGINS", "*")
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "true")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
