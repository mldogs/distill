"""NoveltyAnalyzer - main class for computing novelty scores."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novelty.client import OpenRouterClient
from novelty.schemas import NoveltyResult, CriteriaScores, NOVELTY_CRITERIA

logger = logging.getLogger(__name__)

DEFAULT_CRITERIA_WEIGHTS: dict[str, float] = {c: 1.0 for c in NOVELTY_CRITERIA}


class NoveltyAnalyzer:
    """Analyzes posts for information novelty using LLM."""

    def __init__(
        self,
        session: AsyncSession,
        client: Optional[OpenRouterClient] = None,
        analysis_hours: int = 48,
        context_days: int = 14,
        channel_usernames: Optional[list[str]] = None,
        min_text_length: int = 50,
        max_concurrent: int = 5,
        criteria_weights: Optional[dict[str, float]] = None,
    ):
        self.session = session
        self.client = client or OpenRouterClient()
        self.analysis_hours = analysis_hours
        self.context_days = context_days
        self.channel_usernames = (
            [c.lstrip("@").strip() for c in channel_usernames if c and c.strip()]
            if channel_usernames
            else None
        )
        self.min_text_length = min_text_length
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._criteria_weights = criteria_weights

    async def close(self):
        if self.client:
            await self.client.close()

    async def get_posts_for_analysis(
        self, limit: Optional[int] = None, force: bool = False,
    ) -> list:
        """Get posts that need novelty scoring within analysis_hours window."""
        from sqlalchemy.orm import selectinload
        from storage.models import Post, Channel

        since = datetime.now(timezone.utc) - timedelta(hours=self.analysis_hours)

        query = (
            select(Post)
            .options(selectinload(Post.channel))
            .join(Channel)
            .where(Channel.is_active == True)
            .where(Channel.username.in_(self.channel_usernames) if self.channel_usernames else True)
            .where(Post.posted_at >= since)
            .where(Post.text != None)  # noqa: E711
            .order_by(Post.posted_at.desc())
        )

        if not force:
            query = query.where(Post.novelty_score == None)  # noqa: E711
        if limit:
            query = query.limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_context_posts(self, exclude_post_id: int, limit: int = 300) -> list[str]:
        """Get top context posts by score for comparison."""
        from sqlalchemy import func
        from storage.models import Post, Channel, Score

        since = datetime.now(timezone.utc) - timedelta(days=self.context_days)

        score_subq = (
            select(Score.post_id, func.max(Score.score).label("max_score"))
            .group_by(Score.post_id)
            .subquery()
        )

        query = (
            select(Post.text)
            .join(Channel)
            .outerjoin(score_subq, Post.id == score_subq.c.post_id)
            .where(Channel.is_active == True)
            .where(Channel.username.in_(self.channel_usernames) if self.channel_usernames else True)
            .where(Post.posted_at >= since)
            .where(Post.id != exclude_post_id)
            .where(Post.text != None)  # noqa: E711
            .order_by(score_subq.c.max_score.desc().nulls_last())
            .limit(limit)
        )

        result = await self.session.execute(query)
        return [text for (text,) in result.all() if text and len(text) >= self.min_text_length]

    async def analyze_post(
        self,
        post_id: int,
        post_text: str,
        channel_username: str,
        context_posts: Optional[list[str]] = None,
        criteria_weights: Optional[dict[str, float]] = None,
    ) -> NoveltyResult:
        """Analyze a single post for novelty."""
        async with self._semaphore:
            if context_posts is None:
                context_posts = await self.get_context_posts(post_id)
            if criteria_weights is None:
                criteria_weights = self._criteria_weights or DEFAULT_CRITERIA_WEIGHTS

            if len(post_text) < self.min_text_length:
                return NoveltyResult(
                    post_id=post_id, novelty_score=0.5,
                    criteria_scores=CriteriaScores.neutral(),
                    analysis=None, model_used="skipped", tokens_used=0,
                )

            try:
                analysis, model_used, tokens_used = await self.client.analyze_novelty(
                    post_text=post_text,
                    context_posts=context_posts,
                    channel_name=channel_username,
                )
                weighted_score = analysis.criteria.compute_weighted_score(criteria_weights)
                return NoveltyResult(
                    post_id=post_id, novelty_score=weighted_score,
                    criteria_scores=analysis.criteria, analysis=analysis,
                    model_used=model_used, tokens_used=tokens_used,
                )
            except Exception as e:
                logger.error(f"Failed to analyze post {post_id}: {e}")
                return NoveltyResult(
                    post_id=post_id, novelty_score=0.5,
                    criteria_scores=CriteriaScores.neutral(),
                    analysis=None, model_used="error", tokens_used=0,
                )

    async def analyze_batch(
        self, posts: Sequence, context_posts: Optional[list[str]] = None,
    ) -> list[NoveltyResult]:
        """Analyze multiple posts concurrently."""
        if not posts:
            return []

        if context_posts is None:
            context_posts = await self.get_context_posts(posts[0].id, limit=300)

        criteria_weights = self._criteria_weights or DEFAULT_CRITERIA_WEIGHTS

        tasks = [
            self.analyze_post(
                post_id=post.id,
                post_text=post.text or "",
                channel_username=post.channel.username if post.channel else "unknown",
                context_posts=context_posts,
                criteria_weights=criteria_weights,
            )
            for post in posts
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        valid = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Batch analysis error: {result}")
            else:
                valid.append(result)
        return valid

    async def save_novelty_score(self, post_id: int, result: NoveltyResult) -> None:
        """Save novelty score to database."""
        from storage.models import Post

        stmt = select(Post).where(Post.id == post_id)
        post = (await self.session.execute(stmt)).scalar_one_or_none()
        if post:
            post.novelty_score = result.novelty_score
            post.novelty_explanation = result.to_dict()
            await self.session.flush()

    async def analyze_and_save(
        self, limit: Optional[int] = None, force: bool = False,
    ) -> tuple[int, int]:
        """Analyze posts and save results. Returns (analyzed_count, saved_count)."""
        posts = await self.get_posts_for_analysis(limit, force=force)
        if not posts:
            logger.info("No posts to analyze" + (" (use force=True to re-analyze)" if not force else ""))
            return 0, 0

        logger.info(f"Analyzing {len(posts)} posts for novelty")
        context_posts = await self.get_context_posts(posts[0].id if posts else 0)
        logger.info(f"Using {len(context_posts)} context posts")

        results = await self.analyze_batch(posts, context_posts)

        saved = 0
        for result in results:
            try:
                await self.save_novelty_score(result.post_id, result)
                saved += 1
            except Exception as e:
                logger.error(f"Failed to save novelty for post {result.post_id}: {e}")

        await self.session.commit()
        logger.info(f"Analyzed {len(results)} posts, saved {saved} novelty scores")
        return len(results), saved
