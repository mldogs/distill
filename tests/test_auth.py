"""Tests for authentication module."""
from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from api.auth import (
    create_access_token,
    decode_token,
    parse_telegram_user,
    verify_telegram_auth,
)


class TestJWT:
    """Tests for JWT token creation and decoding."""

    def test_create_and_decode_token(self):
        """Test token creation and decoding returns same user_id."""
        user_id = 42
        token = create_access_token(user_id)

        decoded_id = decode_token(token)

        assert decoded_id == user_id

    def test_decode_invalid_token(self):
        """Test decoding invalid token returns None."""
        result = decode_token("invalid.token.here")

        assert result is None

    def test_decode_empty_token(self):
        """Test decoding empty token returns None."""
        result = decode_token("")

        assert result is None

    def test_decode_malformed_token(self):
        """Test decoding malformed token returns None."""
        result = decode_token("not-even-close-to-jwt")

        assert result is None

    def test_token_contains_user_id(self):
        """Test token payload contains user ID."""
        from jose import jwt
        from api.config import get_settings

        user_id = 123
        token = create_access_token(user_id)
        settings = get_settings()

        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )

        assert payload["sub"] == str(user_id)

    def test_token_contains_expiration(self):
        """Test token payload contains expiration."""
        from jose import jwt
        from api.config import get_settings

        token = create_access_token(1)
        settings = get_settings()

        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )

        assert "exp" in payload
        assert "iat" in payload

    def test_different_users_get_different_tokens(self):
        """Test different users get different tokens."""
        token1 = create_access_token(1)
        token2 = create_access_token(2)

        assert token1 != token2


class TestTelegramAuth:
    """Tests for Telegram Login Widget verification."""

    def _create_valid_auth_data(self, bot_token: str) -> dict:
        """Create valid Telegram auth data with correct hash."""
        data = {
            "id": 123456789,
            "first_name": "Test",
            "last_name": "User",
            "username": "testuser",
            "photo_url": "https://t.me/i/userpic/123.jpg",
            "auth_date": int(time.time()),
        }

        # Create hash
        check_arr = []
        for key, value in sorted(data.items()):
            if value is not None:
                check_arr.append(f"{key}={value}")
        data_check_string = "\n".join(check_arr)

        secret_key = hashlib.sha256(bot_token.encode()).digest()
        hash_value = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        data["hash"] = hash_value
        return data

    def test_verify_valid_auth(self):
        """Test verification of valid Telegram auth data."""
        bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        data = self._create_valid_auth_data(bot_token)

        result = verify_telegram_auth(data, bot_token)

        assert result is True

    def test_verify_invalid_hash(self):
        """Test verification fails with invalid hash."""
        bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        data = {
            "id": 123456789,
            "first_name": "Test",
            "auth_date": int(time.time()),
            "hash": "invalid_hash_value",
        }

        result = verify_telegram_auth(data, bot_token)

        assert result is False

    def test_verify_missing_hash(self):
        """Test verification fails without hash."""
        bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        data = {
            "id": 123456789,
            "first_name": "Test",
            "auth_date": int(time.time()),
        }

        result = verify_telegram_auth(data, bot_token)

        assert result is False

    def test_verify_empty_bot_token(self):
        """Test verification fails with empty bot token."""
        data = {
            "id": 123456789,
            "first_name": "Test",
            "auth_date": int(time.time()),
            "hash": "some_hash",
        }

        result = verify_telegram_auth(data, "")

        assert result is False

    def test_verify_tampered_data(self):
        """Test verification fails if data is tampered."""
        bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        data = self._create_valid_auth_data(bot_token)

        # Tamper with data after hash was created
        data["first_name"] = "Hacker"

        result = verify_telegram_auth(data, bot_token)

        assert result is False

    def test_verify_wrong_bot_token(self):
        """Test verification fails with wrong bot token."""
        correct_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        wrong_token = "654321:ZYX-WVU9876srqPO-dcb21N1m0l987dc00"

        data = self._create_valid_auth_data(correct_token)

        result = verify_telegram_auth(data, wrong_token)

        assert result is False


class TestParseTelegramUser:
    """Tests for Telegram user data parsing."""

    def test_parse_full_user_data(self):
        """Test parsing complete user data."""
        data = {
            "id": 123456789,
            "first_name": "John",
            "last_name": "Doe",
            "username": "johndoe",
            "photo_url": "https://t.me/i/userpic/123.jpg",
        }

        result = parse_telegram_user(data)

        assert result["provider"] == "telegram"
        assert result["provider_id"] == "123456789"
        assert result["username"] == "johndoe"
        assert result["display_name"] == "John Doe"
        assert result["avatar_url"] == "https://t.me/i/userpic/123.jpg"

    def test_parse_minimal_user_data(self):
        """Test parsing minimal user data (only required fields)."""
        data = {
            "id": 123456789,
            "first_name": "John",
        }

        result = parse_telegram_user(data)

        assert result["provider"] == "telegram"
        assert result["provider_id"] == "123456789"
        assert result["username"] is None
        assert result["display_name"] == "John"
        assert result["avatar_url"] is None

    def test_parse_user_without_last_name(self):
        """Test parsing user without last name."""
        data = {
            "id": 123456789,
            "first_name": "John",
            "username": "johndoe",
        }

        result = parse_telegram_user(data)

        assert result["display_name"] == "John"

    def test_parse_user_provider_id_is_string(self):
        """Test provider_id is converted to string."""
        data = {
            "id": 123456789,
            "first_name": "John",
        }

        result = parse_telegram_user(data)

        assert isinstance(result["provider_id"], str)
        assert result["provider_id"] == "123456789"
