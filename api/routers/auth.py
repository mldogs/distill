"""Authentication endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import (
    create_access_token,
    is_telegram_auth_date_fresh,
    parse_telegram_user,
    verify_telegram_auth,
)
from api.config import get_settings
from api.dependencies import get_current_user, get_db_session
from api.schemas import TelegramAuthData, TokenResponse, UserResponse
from storage import User, UserRepository

router = APIRouter()


@router.post("/dev-login", response_model=TokenResponse, include_in_schema=True)
async def dev_login(
    username: str = "test_user",
    session: AsyncSession = Depends(get_db_session),
):
    """
    Development-only login endpoint.
    Creates a test user and returns JWT token.

    WARNING: Disable in production!
    """
    settings = get_settings()
    if not settings.enable_dev_login:
        # Hide dev login unless explicitly enabled.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    user_repo = UserRepository(session)
    user = await user_repo.create_or_update(
        provider="dev",
        provider_id=f"dev_{username}",
        username=username,
        display_name=f"Dev User ({username})",
    )

    token = create_access_token(user.id)

    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user.id,
            provider=user.provider,
            username=user.username,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            is_admin=settings.is_admin_user(
                user.id,
                provider=user.provider,
                provider_id=user.provider_id,
            ),
        ),
    )


@router.post("/telegram", response_model=TokenResponse)
async def auth_telegram(
    data: TelegramAuthData,
    session: AsyncSession = Depends(get_db_session),
):
    """Authenticate via Telegram Login Widget."""
    settings = get_settings()

    # Verify Telegram hash
    auth_data = data.model_dump()
    if not verify_telegram_auth(auth_data, settings.telegram_bot_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Telegram authentication",
        )

    # Anti-replay: reject old auth_date (Telegram signs auth_date as part of the payload).
    if not is_telegram_auth_date_fresh(
        auth_data["auth_date"],
        ttl_seconds=settings.telegram_auth_ttl_seconds,
        clock_skew_seconds=settings.telegram_auth_clock_skew_seconds,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Telegram authentication expired",
        )

    # Parse user info
    user_info = parse_telegram_user(auth_data)

    # Create or update user
    user_repo = UserRepository(session)
    user = await user_repo.create_or_update(**user_info)

    # Create JWT token
    token = create_access_token(user.id)

    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user.id,
            provider=user.provider,
            username=user.username,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            is_admin=settings.is_admin_user(
                user.id,
                provider=user.provider,
                provider_id=user.provider_id,
            ),
        ),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    """Get current authenticated user."""
    settings = get_settings()
    return UserResponse(
        id=user.id,
        provider=user.provider,
        username=user.username,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        is_admin=settings.is_admin_user(
            user.id,
            provider=user.provider,
            provider_id=user.provider_id,
        ),
    )
