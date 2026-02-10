"""Authentication utilities: JWT and OAuth verification."""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from api.config import get_settings


def create_access_token(user_id: int, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token for user."""
    settings = get_settings()
    if expires_delta is None:
        expires_delta = timedelta(hours=settings.jwt_expire_hours)

    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[int]:
    """Decode JWT token and return user_id, or None if invalid."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = payload.get("sub")
        if user_id is None:
            return None
        return int(user_id)
    except (JWTError, ValueError):
        return None


def is_telegram_auth_date_fresh(
    auth_date: int,
    *,
    ttl_seconds: int,
    clock_skew_seconds: int = 60,
    now: datetime | None = None,
) -> bool:
    """
    Validate Telegram Login Widget auth_date for replay protection.

    Telegram signs auth_date, so once HMAC is verified we only need a freshness check.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())
    if auth_date > now_ts + clock_skew_seconds:
        return False
    return (now_ts - auth_date) <= ttl_seconds


def verify_telegram_auth(data: dict, bot_token: str) -> bool:
    """
    Verify Telegram Login Widget authentication data.

    Telegram auth uses HMAC-SHA256:
    1. Create data_check_string from sorted key=value pairs (excluding hash)
    2. secret_key = SHA256(bot_token)
    3. Verify HMAC-SHA256(data_check_string, secret_key) == hash
    """
    if not bot_token:
        return False

    check_hash = data.get("hash")
    if not check_hash:
        return False

    # Build data-check-string
    check_arr = []
    for key, value in sorted(data.items()):
        if key != "hash" and value is not None:
            check_arr.append(f"{key}={value}")
    data_check_string = "\n".join(check_arr)

    # Create secret key from bot token
    secret_key = hashlib.sha256(bot_token.encode()).digest()

    # Compute HMAC
    computed_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed_hash, check_hash)


def parse_telegram_user(data: dict) -> dict:
    """Parse Telegram auth data into user info dict."""
    display_name = data.get("first_name", "")
    if data.get("last_name"):
        display_name += f" {data['last_name']}"

    return {
        "provider": "telegram",
        "provider_id": str(data["id"]),
        "username": data.get("username"),
        "display_name": display_name or None,
        "avatar_url": data.get("photo_url"),
    }
