"""Stats endpoint - system statistics."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session
from api.schemas import StatsResponse
from ranker.periods import PeriodMode, compute_period_hash, get_bucketed_period_bounds, parse_period
from storage.models import Channel, Post, Score, User, Vote

router = APIRouter()


def _get_period_start(period: str) -> datetime | None:
    """Get start datetime for period. Returns None for 'all'."""
    now = datetime.now(timezone.utc)
    if period in ("daily", "24h"):
        return now - timedelta(days=1)
    elif period in ("weekly", "7d"):
        return now - timedelta(days=7)
    elif period in ("monthly", "30d"):
        return now - timedelta(days=30)
    elif period.lower().strip() == "all":
        return None
    else:
        return now - timedelta(days=7)  # default to weekly


async def _get_avg_score(
    session: AsyncSession, period: str, is_all_time: bool, period_end: datetime,
) -> float:
    """Get average score: try stored v4 scores by period_hash, fall back to global avg."""
    sample_limits = {
        "daily": 500, "24h": 500,
        "weekly": 200, "7d": 200,
        "monthly": 2000, "30d": 2000,
    }
    sample_limit = sample_limits.get(period, 1000)

    # For "all time" or when we can't match a period_hash, use global avg
    if is_all_time:
        avg = await session.scalar(
            select(func.avg(Score.score)).where(Score.formula_version == "v4")
        )
        return round(avg, 1) if avg else 0.0

    # Try matching the exact stored score bucket
    try:
        period_enum = parse_period(period)
        bucket_start, bucket_end = get_bucketed_period_bounds(
            period_enum, reference=period_end, mode=PeriodMode.ROLLING,
        )
        period_hash = compute_period_hash(
            period=period_enum, period_start=bucket_start,
            period_end=bucket_end, mode=PeriodMode.ROLLING,
        )
        top_scores_subq = (
            select(Score.score)
            .where(Score.formula_version == "v4", Score.period_hash == period_hash)
            .order_by(Score.score.desc())
            .limit(sample_limit)
            .subquery()
        )
        avg = await session.scalar(select(func.avg(top_scores_subq.c.score)))
        if avg:
            return round(avg, 1)
    except Exception:
        pass

    # Fallback: global avg of all stored v4 scores
    avg = await session.scalar(
        select(func.avg(Score.score)).where(Score.formula_version == "v4")
    )
    return round(avg, 1) if avg else 0.0


@router.get("", response_model=StatsResponse)
async def get_stats(
    session: AsyncSession = Depends(get_db_session),
    period: Optional[str] = Query(None, description="Period for posts count (daily, weekly, monthly)"),
):
    """Get system statistics."""
    channels_count = await session.scalar(
        select(func.count(Channel.id)).where(Channel.is_active == True)  # noqa: E712
    )
    votes_count = await session.scalar(select(func.count(Vote.id)))
    users_count = await session.scalar(select(func.count(User.id)))

    period_start = _get_period_start(period) if period else None
    is_all_time = period is not None and period_start is None
    period_end = datetime.now(timezone.utc)

    # Posts count
    posts_query = select(func.count(Post.id))
    if period_start is not None:
        posts_query = posts_query.where(Post.posted_at >= period_start)
    posts_count = await session.scalar(posts_query) or 0

    # Avg score
    avg_score = await _get_avg_score(session, period or "all", period_start is None, period_end)

    return StatsResponse(
        channels_count=channels_count or 0,
        posts_count=posts_count or 0,
        scores_count=0,  # deprecated
        votes_count=votes_count or 0,
        users_count=users_count or 0,
        avg_score=avg_score,
    )
