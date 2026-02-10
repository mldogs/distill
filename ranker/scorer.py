"""Scorer for batch ranking posts."""
from __future__ import annotations


from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from ranker.features import PostFeatures, extract_features
from ranker.formulas import Formula, ScoreResult, get_formula, build_formula
from ranker.periods import (
    Period,
    PeriodMode,
    get_period_bounds,
    get_bucketed_period_bounds,
    compute_period_hash,
)
from storage.models import Post
from storage.repositories import PostRepository, ScoreRepository


class Scorer:
    """
    Main class for scoring posts in batch.

    Handles fetching posts, computing scores, and saving results.
    """

    def __init__(
        self,
        session: AsyncSession,
        formula: Formula | str,
        global_avg_posts_per_day: float | None = None,
        default_limit: int = 50000,
        period: Period | None = None,
    ):
        """
        Initialize scorer.

        Args:
            session: Async database session
            formula: Formula instance or version string ('v0', 'v1')
            global_avg_posts_per_day: Dynamic average posts per day across all channels (v4)
            default_limit: Default max posts to process if not specified (default: 50000)
            period: Period type for adaptive decay rates (recommended for scheduled tasks)
        """
        self.session = session

        # Build formula with period-aware decay if period provided
        if isinstance(formula, str) and period is not None:
            # Only pass avg_posts_per_day for formulas that support it (v4)
            kwargs = {"period": period}
            if global_avg_posts_per_day is not None and formula in ("v4",):
                kwargs["avg_posts_per_day"] = global_avg_posts_per_day
            self.formula = build_formula(formula, **kwargs)
        elif isinstance(formula, Formula):
            self.formula = formula
        else:
            self.formula = get_formula(formula)

        self.post_repo = PostRepository(session)
        self.score_repo = ScoreRepository(session)
        self.global_avg_posts_per_day = global_avg_posts_per_day
        self.default_limit = default_limit
        self.period = period

    async def rank_period(
        self,
        period_start: datetime,
        period_end: datetime,
        limit: int | None = None,
        reference_time: datetime | None = None,
    ) -> list[ScoreResult]:
        """
        Compute scores for posts in a time period.

        Args:
            period_start: Start of period
            period_end: End of period
            limit: Max posts to process (None = use default_limit)
            reference_time: Reference time for age calculation (default: period_end)

        Returns:
            List of ScoreResult sorted by score descending
        """
        import logging
        logger = logging.getLogger(__name__)

        # Use default_limit if not provided
        if limit is None:
            limit = self.default_limit

        # Fetch posts for the period
        posts = await self.post_repo.get_by_period(
            start=period_start,
            end=period_end,
            limit=limit,
        )

        # Warn if we hit the limit (might be truncating results)
        if len(posts) >= limit:
            logger.warning(
                f"Fetched {len(posts)} posts (limit={limit}). "
                f"Period: {period_start} to {period_end}. "
                f"Consider increasing default_limit or filtering by channel."
            )

        # Use period_end as reference_time if not provided
        if reference_time is None:
            reference_time = period_end

        # Compute scores
        results = self._compute_scores(posts, reference_time=reference_time)

        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)

        return results

    async def rank_by_period_type(
        self,
        period: Period,
        reference_time: datetime | None = None,
        limit: int | None = None,
        mode: PeriodMode = PeriodMode.ROLLING,
        use_bucketed_bounds: bool = True,
    ) -> list[ScoreResult]:
        """
        Compute scores for a standard period type.

        Args:
            period: Period type (DAILY, WEEKLY, MONTHLY)
            reference_time: Reference time (default: now)
            limit: Max posts to process
            mode: Period mode (ROLLING or CALENDAR)
            use_bucketed_bounds: If True, use bucketed boundaries for stable periods

        Returns:
            List of ScoreResult sorted by score descending
        """
        if use_bucketed_bounds:
            start, end = get_bucketed_period_bounds(period, reference_time, mode)
        else:
            start, end = get_period_bounds(period, reference_time)
        return await self.rank_period(start, end, limit)

    def _compute_scores(
        self,
        posts: Sequence[Post],
        reference_time: datetime | None = None,
    ) -> list[ScoreResult]:
        """
        Compute scores for a list of posts.

        Args:
            posts: List of Post objects
            reference_time: Reference time for age calculation

        Returns:
            List of ScoreResult
        """
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        results = []
        for post in posts:
            features = extract_features(
                post,
                reference_time,
                global_avg_posts_per_day=self.global_avg_posts_per_day,
            )
            result = self.formula.score(features)
            results.append(result)

        return results

    async def save_scores(
        self,
        scores: list[ScoreResult],
        period_start: datetime,
        period_end: datetime,
        period: Period | None = None,
        mode: PeriodMode = PeriodMode.ROLLING,
    ) -> int:
        """
        Save computed scores to database.

        Args:
            scores: List of ScoreResult to save
            period_start: Period start for score records
            period_end: Period end for score records
            period: Period type (for hash computation, optional)
            mode: Period mode (for hash computation)

        Returns:
            Number of rows affected
        """
        if not scores:
            return 0

        # Compute period_hash if period is provided
        period_hash = None
        if period is not None:
            period_hash = compute_period_hash(
                period=period,
                period_start=period_start,
                period_end=period_end,
                mode=mode,
            )

        scores_data = [
            {
                "post_id": s.post_id,
                "formula_version": self.formula.name,
                "score": s.score,
                "period_start": period_start,
                "period_end": period_end,
                "period_hash": period_hash,
                "global_avg_used": self.global_avg_posts_per_day,
                "explanation": s.explanation,
            }
            for s in scores
        ]

        return await self.score_repo.bulk_upsert_scores(scores_data)

    async def rank_and_save(
        self,
        period_start: datetime,
        period_end: datetime,
        limit: int | None = None,
        period: Period | None = None,
        mode: PeriodMode = PeriodMode.ROLLING,
    ) -> tuple[list[ScoreResult], int]:
        """
        Compute and save scores in one operation.

        Args:
            period_start: Start of period
            period_end: End of period
            limit: Max posts to process
            period: Period type (for hash computation, optional)
            mode: Period mode (for hash computation)

        Returns:
            Tuple of (scores list, rows saved count)
        """
        scores = await self.rank_period(period_start, period_end, limit)
        saved = await self.save_scores(scores, period_start, period_end, period, mode)
        return scores, saved

    async def rank_and_save_by_period_type(
        self,
        period: Period,
        reference_time: datetime | None = None,
        limit: int | None = None,
        mode: PeriodMode = PeriodMode.ROLLING,
        use_bucketed_bounds: bool = True,
    ) -> tuple[list[ScoreResult], int]:
        """
        Compute and save scores for a standard period type.

        Args:
            period: Period type
            reference_time: Reference time
            limit: Max posts
            mode: Period mode (ROLLING or CALENDAR)
            use_bucketed_bounds: If True, use bucketed boundaries for stable periods

        Returns:
            Tuple of (scores list, rows saved count)
        """
        if use_bucketed_bounds:
            start, end = get_bucketed_period_bounds(period, reference_time, mode)
        else:
            start, end = get_period_bounds(period, reference_time)

        scores = await self.rank_period(start, end, limit)
        saved = await self.save_scores(scores, start, end, period=period, mode=mode)
        return scores, saved


def score_posts_sync(
    posts: Sequence[Post],
    formula: Formula | str,
    reference_time: datetime | None = None,
    global_avg_posts_per_day: float | None = None,
) -> list[ScoreResult]:
    """
    Synchronous utility to score posts without database.

    Useful for testing or one-off computations.

    Args:
        posts: List of Post objects
        formula: Formula instance or version string
        reference_time: Reference time for age calculation
        global_avg_posts_per_day: Dynamic average posts per day across all channels (v4)

    Returns:
        List of ScoreResult sorted by score descending
    """
    if isinstance(formula, str):
        formula = get_formula(formula)

    if reference_time is None:
        reference_time = datetime.now(timezone.utc)

    results = []
    for post in posts:
        features = extract_features(
            post,
            reference_time,
            global_avg_posts_per_day=global_avg_posts_per_day,
        )
        result = formula.score(features)
        results.append(result)

    results.sort(key=lambda r: r.score, reverse=True)
    return results
