"""API configuration from environment variables."""
from __future__ import annotations

import secrets
from typing import List, Literal, Set

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


AppEnv = Literal["dev", "test", "prod"]


_INSECURE_JWT_SECRETS = {
    "",
    "change-me-in-production",
    "changeme",
    "secret",
    "jwt_secret",
    "password",
}


class Settings(BaseSettings):
    """API settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment
    app_env: AppEnv = "prod"

    # Auth/dev-only
    enable_dev_login: bool = False

    # JWT
    # Empty means "unset". In dev/test, we generate an ephemeral secret; in prod this is forbidden.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24 * 7  # 1 week

    # Telegram OAuth
    telegram_bot_token: str = ""
    telegram_auth_ttl_seconds: int = 24 * 60 * 60  # 24h anti-replay window
    telegram_auth_clock_skew_seconds: int = 60  # allow small client/server clock drift

    # Google OAuth (optional)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # CORS (use CORS_ORIGINS env var, comma-separated, or "*" for all)
    cors_origins: str = "http://localhost:3000,http://localhost:8501"
    cors_allow_credentials: bool = True

    # Admin access
    # Comma-separated IDs or "all" for dev/test ONLY.
    #
    # Note: IDs are treated as Telegram user IDs when provider_id is numeric.
    # For non-numeric provider_id providers, we fall back to the internal users.id.
    admin_ids: str = ""

    # API
    api_title: str = "Telegram Post Exchange API"
    api_version: str = "0.1.0"

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins from comma-separated string."""
        value = (self.cors_origins or "").strip()
        if value == "*":
            return ["*"]
        return [o.strip() for o in value.split(",") if o.strip()]

    def _parse_admin_ids_set(self) -> Set[int]:
        raw = (self.admin_ids or "").strip()
        if not raw:
            return set()
        ids: set[int] = set()
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.add(int(part))
            except ValueError as exc:
                raise ValueError(f"ADMIN_IDS contains non-integer value: {part!r}") from exc
        return ids

    def is_admin_user(
        self,
        user_id: int,
        *,
        provider: str | None = None,
        provider_id: str | None = None,
    ) -> bool:
        """Check if a user has admin access based on settings.ADMIN_IDS."""
        if self.admin_ids == "all":
            return True

        allowed = self._parse_admin_ids_set()
        if not allowed:
            return False

        # Prefer numeric provider_id (Telegram user ID) when available.
        if provider_id:
            provider_id = provider_id.strip()
            if provider_id.isdigit():
                return int(provider_id) in allowed

        # Fallback: internal users.id (useful for non-numeric providers).
        return user_id in allowed

    @model_validator(mode="after")
    def _validate_security(self) -> "Settings":
        self.app_env = self.app_env.strip().lower()  # type: ignore[assignment]

        # Normalize common string fields
        self.jwt_secret = (self.jwt_secret or "").strip()
        self.admin_ids = (self.admin_ids or "").strip().lower()
        self.cors_origins = (self.cors_origins or "").strip()

        # --- Dev login gating ---
        if self.app_env == "prod" and self.enable_dev_login:
            raise ValueError("ENABLE_DEV_LOGIN must be false in APP_ENV=prod")

        # --- JWT secret ---
        if not self.jwt_secret:
            if self.app_env == "prod":
                raise ValueError("JWT_SECRET must be set (non-empty) in APP_ENV=prod")
            # Dev/test: generate ephemeral secret (safe by default for local usage).
            self.jwt_secret = secrets.token_urlsafe(32)

        if self.app_env == "prod":
            if self.jwt_secret.lower() in _INSECURE_JWT_SECRETS:
                raise ValueError("JWT_SECRET is insecure/placeholder in APP_ENV=prod")
            if len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET is too short in APP_ENV=prod (min 32 chars)")

        # --- Admin IDs ---
        if not self.admin_ids:
            if self.app_env == "prod":
                raise ValueError("ADMIN_IDS must be set in APP_ENV=prod")
            # Dev/test default for convenience.
            self.admin_ids = "all"

        if self.admin_ids == "all" and self.app_env == "prod":
            raise ValueError("ADMIN_IDS=all is forbidden in APP_ENV=prod")

        if self.admin_ids != "all":
            _ = self._parse_admin_ids_set()  # validate format

        # --- CORS ---
        if not self.cors_origins:
            if self.app_env == "prod":
                raise ValueError("CORS_ORIGINS must be set in APP_ENV=prod")
            self.cors_origins = "http://localhost:3000"

        # Never allow "*" + credentials (force safe).
        if "*" in self.cors_origins_list:
            self.cors_allow_credentials = False

        if self.telegram_auth_ttl_seconds <= 0:
            raise ValueError("TELEGRAM_AUTH_TTL_SECONDS must be > 0")
        if self.telegram_auth_clock_skew_seconds < 0:
            raise ValueError("TELEGRAM_AUTH_CLOCK_SKEW_SECONDS must be >= 0")

        return self


_settings: Settings | None = None


def get_settings() -> Settings:
    """Get cached settings instance (validated)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset cached settings (useful for tests)."""
    global _settings
    _settings = None
