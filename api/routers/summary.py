"""Summary endpoint - get generated summaries."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db_session
from api.schemas import SummaryResponse
from storage import SummaryRepository

router = APIRouter()


@router.get("", response_model=SummaryResponse)
async def get_latest_summary(
    period: str = Query("weekly", description="Period type: daily, weekly, monthly"),
    formula: Optional[str] = Query(None, description="Filter by formula version"),
    session: AsyncSession = Depends(get_db_session),
):
    """Get the latest summary for a period type."""
    summary_repo = SummaryRepository(session)
    summaries = await summary_repo.get_latest(period_type=period, limit=1)

    if not summaries:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {period} summary found",
        )

    summary = summaries[0]

    # Filter by formula if specified
    if formula and summary.formula_version != formula:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {period} summary found for formula {formula}",
        )

    return SummaryResponse(
        id=summary.id,
        period_type=summary.period_type,
        period_start=summary.period_start,
        period_end=summary.period_end,
        title=summary.title,
        content_markdown=summary.content_markdown,
        formula_version=summary.formula_version,
        post_count=summary.post_count,
        channel_count=summary.channel_count,
    )
