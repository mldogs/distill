"""Feed endpoint - get ranked posts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional, Sequence

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.dependencies import get_db_session
from api.schemas import FeedResponse, PostResponse, post_to_response
from ranker import Scorer, get_formula
from ranker.formulas import ScoreResult
from ranker.periods import (
    Period,
    PeriodMode,
    get_bucketed_period_bounds,
    compute_period_hash,
    parse_period,
)
from storage.models import Channel, Post, Score

router = APIRouter()


SortBy = Literal["score", "posted_at", "views", "replies", "reactions", "forwards", "novelty"]
SortDir = Literal["desc", "asc"]


def _coalesced_metric(sort_key: SortBy):
    """Map sort key to a coalesced SQL expression on Post."""
    if sort_key == "views":
        return func.coalesce(Post.views, 0)
    if sort_key == "replies":
        return func.coalesce(Post.replies, 0)
    if sort_key == "reactions":
        return func.coalesce(Post.reactions_count, 0)
    if sort_key == "forwards":
        return func.coalesce(Post.forwards, 0)
    if sort_key == "novelty":
        return func.coalesce(Post.novelty_score, 0.0)
    if sort_key == "posted_at":
        return Post.posted_at
    return None


def _build_order_by(sort_by: SortBy, sort_dir: SortDir, score_col=None) -> list:
    """Build unified ORDER BY clause list.

    score_col: the column/expression to use for score ordering (e.g. Score.score
    or a subquery column).  When sort_by=="score", score_col is primary;
    otherwise a metric column is primary and score_col is secondary.
    """
    clauses = []
    if sort_by == "score":
        if score_col is not None:
            clauses.append(score_col.desc() if sort_dir == "desc" else score_col.asc())
    else:
        metric = _coalesced_metric(sort_by)
        if metric is not None:
            clauses.append(metric.desc() if sort_dir == "desc" else metric.asc())
        if score_col is not None:
            clauses.append(score_col.desc())
    clauses.extend([Post.posted_at.desc(), Post.id.desc()])
    return clauses


def _python_dedup(
    score_results: Sequence[ScoreResult],
    posts_by_id: dict[int, Post],
    sort_dir: SortDir,
) -> list[PostResponse]:
    """Deduplicate scored posts by (channel_id, grouped_id) in Python."""
    score_results = sorted(score_results, key=lambda r: r.score, reverse=(sort_dir == "desc"))
    seen_groups: set[tuple[int, int]] = set()
    deduped: list[PostResponse] = []
    for r in score_results:
        post = posts_by_id.get(r.post_id)
        if post is None:
            continue
        if post.grouped_id is not None:
            group_key = (post.channel_id, post.grouped_id)
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)
        deduped.append(post_to_response(post=post, score=r.score, explanation=r.explanation))
    return deduped


async def _make_scorer(
    session: AsyncSession, formula_name: str, period: Period,
) -> Scorer:
    """Create a Scorer, fetching global_avg_posts_per_day for v4."""
    global_avg: float | None = None
    if formula_name == "v4":
        global_avg = await session.scalar(
            select(func.avg(Channel.posts_per_day_30d)).where(
                Channel.is_active == True,  # noqa: E712
                Channel.posts_per_day_30d != None,  # noqa: E711
                Channel.posts_per_day_30d > 0,
            )
        )
    return Scorer(session, formula_name, global_avg_posts_per_day=global_avg, period=period)


async def _feed_sorted_by_metric(
    session: AsyncSession,
    scorer: Scorer,
    sort_by: SortBy,
    sort_dir: SortDir,
    post_filters: list,
    dedup_partition: list,
    dedup_key,
    period_end: datetime,
    offset: int,
    limit: int,
) -> tuple[list[PostResponse], int]:
    """Fetch posts sorted by a non-score metric, compute scores after fetch."""
    order_by = _build_order_by(sort_by, sort_dir)

    total = (
        await session.scalar(
            select(func.count(func.distinct(dedup_key)))
            .select_from(Post)
            .where(*post_filters)
        )
    ) or 0

    ranked_posts = (
        select(
            Post.id.label("post_id"),
            func.row_number()
            .over(partition_by=dedup_partition, order_by=order_by)
            .label("rn"),
        )
        .where(*post_filters)
        .subquery()
    )

    posts_query = (
        select(Post)
        .join(ranked_posts, ranked_posts.c.post_id == Post.id)
        .options(selectinload(Post.channel))
        .where(ranked_posts.c.rn == 1)
        .order_by(*order_by)
        .offset(offset)
        .limit(limit)
    )
    posts = list((await session.execute(posts_query)).scalars().all())

    score_results = scorer._compute_scores(posts, reference_time=period_end)
    scores_by_id = {r.post_id: r for r in score_results}
    response_posts = [
        post_to_response(
            post=p,
            score=scores_by_id[p.id].score,
            explanation=scores_by_id[p.id].explanation,
        )
        for p in posts
    ]
    return response_posts, total


async def _feed_sorted_by_score(
    session: AsyncSession,
    scorer: Scorer,
    sort_dir: SortDir,
    post_filters: list,
    dedup_key,
    period_end: datetime,
    offset: int,
    limit: int,
) -> tuple[list[PostResponse], int]:
    """Fetch candidate posts, score them all, sort by score, deduplicate in Python."""
    total = (
        await session.scalar(
            select(func.count(func.distinct(dedup_key)))
            .select_from(Post)
            .where(*post_filters)
        )
    ) or 0

    buffer = 2000
    candidate_limit = min(offset + limit + buffer, 5000)
    posts_query = (
        select(Post)
        .options(selectinload(Post.channel))
        .where(*post_filters)
        .order_by(Post.posted_at.desc(), Post.id.desc())
        .limit(candidate_limit)
    )
    posts = list((await session.execute(posts_query)).scalars().all())

    score_results = scorer._compute_scores(posts, reference_time=period_end)
    posts_by_id = {p.id: p for p in posts}
    deduped = _python_dedup(score_results, posts_by_id, sort_dir)

    return deduped[offset:offset + limit], total


@router.get("", response_model=FeedResponse)
async def get_feed(
    period: str = Query("weekly", description="Period: 24h, daily, 7d, weekly, 30d, monthly, all"),
    limit: int = Query(50, ge=1, le=100, description="Number of posts to return"),
    offset: int = Query(0, ge=0, description="Number of posts to skip (for pagination)"),
    formula: str = Query("v4", description="Scoring formula: v2 (channel-relative), v3 (v2+novelty), v4 (v3+anti-spam)"),
    channel: Optional[str] = Query(None, description="Filter by channel username"),
    min_views: Optional[int] = Query(None, ge=0, description="Filter: minimum views (NULL treated as 0)"),
    min_replies: Optional[int] = Query(None, ge=0, description="Filter: minimum replies (NULL treated as 0)"),
    min_reactions: Optional[int] = Query(None, ge=0, description="Filter: minimum reactions (NULL treated as 0)"),
    min_forwards: Optional[int] = Query(None, ge=0, description="Filter: minimum forwards (NULL treated as 0)"),
    min_novelty: Optional[float] = Query(None, ge=0, le=1, description="Filter: minimum novelty score 0..1 (NULL treated as 0)"),
    sort_by: SortBy = Query("score", description="Sort: score, posted_at, views, replies, reactions, forwards, novelty"),
    sort_dir: SortDir = Query("desc", description="Sort direction: desc or asc"),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get top ranked posts for a period.

    Returns posts sorted by score descending with full post details and score explanation.
    """
    # Parse period ("all" = no time filter, always dynamic scoring)
    is_all_time = period.lower().strip() == "all"

    if is_all_time:
        period_enum = Period.ALL
    else:
        try:
            period_enum = parse_period(period)
        except ValueError:
            period_enum = Period.WEEKLY

    # Get formula
    try:
        formula_obj = get_formula(formula)
    except ValueError:
        formula_obj = get_formula("v4")

    normalized_channel = channel.lower().lstrip("@") if channel else None
    channel_id: int | None = None
    if normalized_channel:
        channel_id = await session.scalar(
            select(Channel.id).where(func.lower(Channel.username) == normalized_channel)
        )
        if channel_id is None:
            return FeedResponse(posts=[], total=0, period=period, formula=formula_obj.name)

    now = datetime.now(timezone.utc)

    if is_all_time:
        period_end = now
        period_hash = None
    else:
        period_start, period_end = get_bucketed_period_bounds(
            period_enum, reference=now, mode=PeriodMode.ROLLING,
        )
        period_hash = compute_period_hash(
            period=period_enum, period_start=period_start,
            period_end=period_end, mode=PeriodMode.ROLLING,
        )

    # Build common post filters
    post_filters = []
    if not is_all_time:
        post_filters.extend([Post.posted_at >= period_start, Post.posted_at <= period_end])
    if channel_id is not None:
        post_filters.append(Post.channel_id == channel_id)
    for key, val in [("views", min_views), ("replies", min_replies),
                      ("reactions", min_reactions), ("forwards", min_forwards),
                      ("novelty", min_novelty)]:
        if val is not None:
            post_filters.append(_coalesced_metric(key) >= val)

    dedup_partition = [Post.channel_id, func.coalesce(Post.grouped_id, Post.id)]
    dedup_key = tuple_(*dedup_partition)

    # PATH 1: Stored v4 scores (fast path, not available for "all time")
    if formula_obj.name == "v4" and period_hash is not None:
        required_window = max(offset + limit, 10)
        stored_total = (
            await session.scalar(
                select(func.count(func.distinct(dedup_key)))
                .select_from(Score)
                .join(Post, Score.post_id == Post.id)
                .where(
                    Score.formula_version == formula_obj.name,
                    Score.period_hash == period_hash,
                    *post_filters,
                )
            )
        ) or 0

        if stored_total >= required_window:
            stored_order = _build_order_by(sort_by, sort_dir, score_col=Score.score)

            ranked_scores = (
                select(
                    Score.post_id.label("post_id"),
                    Score.score.label("score"),
                    Score.explanation.label("explanation"),
                    func.row_number()
                    .over(partition_by=dedup_partition, order_by=stored_order)
                    .label("rn"),
                )
                .join(Post, Score.post_id == Post.id)
                .where(
                    Score.formula_version == formula_obj.name,
                    Score.period_hash == period_hash,
                    *post_filters,
                )
                .subquery()
            )

            deduped_order = _build_order_by(sort_by, sort_dir, score_col=ranked_scores.c.score)

            page_query = (
                select(Post, ranked_scores.c.score, ranked_scores.c.explanation)
                .join(ranked_scores, ranked_scores.c.post_id == Post.id)
                .options(selectinload(Post.channel))
                .where(ranked_scores.c.rn == 1)
                .order_by(*deduped_order)
                .offset(offset)
                .limit(limit)
            )
            rows = (await session.execute(page_query)).all()
            response_posts = [
                post_to_response(post=row[0], score=row[1], explanation=row[2] or {})
                for row in rows
            ]

            return FeedResponse(
                posts=response_posts, total=stored_total,
                period=period, formula=formula_obj.name,
            )

    # PATH 2: Dynamic scoring (all formulas, including v4 fallback)
    scorer = await _make_scorer(session, formula_obj.name, period_enum)

    if sort_by != "score":
        response_posts, total = await _feed_sorted_by_metric(
            session, scorer, sort_by, sort_dir, post_filters,
            dedup_partition, dedup_key, period_end, offset, limit,
        )
    else:
        response_posts, total = await _feed_sorted_by_score(
            session, scorer, sort_dir, post_filters,
            dedup_key, period_end, offset, limit,
        )

    return FeedResponse(
        posts=response_posts, total=total,
        period=period, formula=formula_obj.name,
    )
