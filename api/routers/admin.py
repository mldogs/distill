"""Admin endpoints for manual operations (requires admin auth)."""
from __future__ import annotations

import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.dependencies import get_current_admin
from storage import User

router = APIRouter(dependencies=[Depends(get_current_admin)])


@router.get("/config")
async def get_config():
    """Get admin configuration status."""
    return {
        "openrouter_configured": bool(os.environ.get("OPENROUTER_API_KEY")),
        "telegram_configured": bool(os.environ.get("TG_API_ID") and os.environ.get("TG_API_HASH")),
    }


class CollectRequest(BaseModel):
    """Request to collect posts from channel(s)."""
    channel: Optional[str] = None  # None = all channels
    since_days: int = 7
    limit: Optional[int] = None
    mode: str = "window"  # window|incremental|refresh_recent (default: window for backward compatibility)


class CollectResponse(BaseModel):
    """Response from collect operation."""
    status: str
    task_id: Optional[str] = None
    channels: Optional[list[str]] = None
    message: str


class AddChannelRequest(BaseModel):
    """Request to add a channel."""
    username: str
    name: Optional[str] = None


class AddChannelResponse(BaseModel):
    """Response from add channel operation."""
    status: str
    channel_id: int
    username: str


class ChannelInfo(BaseModel):
    """Channel info for listing."""
    id: int
    username: str
    name: Optional[str]
    is_active: bool
    posts_count: int = 0


class BulkImportRequest(BaseModel):
    """Request to import multiple channels."""
    channels: list[str]  # List of usernames (one per line in txt)
    since_days: int = 7
    auto_rank: bool = True


class BulkImportResponse(BaseModel):
    """Response from bulk import."""
    status: str
    task_id: str
    channels_count: int
    message: str


class IngestRequest(BaseModel):
    """Request to ingest (add + collect) one or more channels."""
    channels: list[str]  # List of channel usernames
    mode: str = "window"  # incremental|refresh_recent|window
    since_days: int = 7  # Used only for window mode
    limit: Optional[int] = None
    auto_rank: bool = False  # Optional: trigger ranking after ingestion


class IngestResponse(BaseModel):
    """Response from ingest operation."""
    status: str
    task_id: str
    channels_count: int
    normalized_channels: list[str]
    message: str


@router.post("/collect", response_model=CollectResponse)
async def trigger_collect(request: CollectRequest):
    """
    Trigger post collection from Telegram.

    - If channel is specified, fetches only that channel
    - If channel is None, fetches all active channels

    Note: Requires Celery worker to be running.
    """
    try:
        from jobs.tasks import fetch_channel, fetch_all_channels
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Celery tasks not available. Is the worker running?"
        )

    if request.channel:
        # Fetch single channel
        result = fetch_channel.delay(
            request.channel,
            limit=request.limit,
            since_days=request.since_days,
            mode=request.mode,
        )
        return CollectResponse(
            status="scheduled",
            task_id=str(result.id),
            channels=[request.channel],
            message=f"Scheduled fetch for {request.channel} (mode={request.mode})",
        )
    else:
        # Fetch all channels
        result = fetch_all_channels.delay(
            limit=request.limit,
            since_days=request.since_days,
            mode=request.mode,
        )
        return CollectResponse(
            status="scheduled",
            task_id=str(result.id),
            message=f"Scheduled fetch for all active channels (mode={request.mode})",
        )


@router.post("/channel", response_model=AddChannelResponse)
async def add_channel(request: AddChannelRequest):
    """
    Add a new channel to the database.

    The channel will be marked as active and included in automatic fetches.
    """
    from storage import get_database, ChannelRepository

    # Normalize username - match frontend sanitization
    # Remove @, trim whitespace, take first word only
    username = request.username.replace("@", "").strip().split()[0] if request.username.strip() else ""

    if not username:
        raise HTTPException(status_code=400, detail="Invalid channel username")

    db = get_database()
    async with db.session() as session:
        repo = ChannelRepository(session)

        # Check if exists
        existing = await repo.get_by_username(username)
        if existing:
            return AddChannelResponse(
                status="exists",
                channel_id=existing.id,
                username=existing.username,
            )

        # Upsert channel (creates new or updates existing)
        channel = await repo.upsert(
            username=username,
            name=request.name or username,
        )
        await session.commit()

        return AddChannelResponse(
            status="created",
            channel_id=channel.id,
            username=channel.username,
        )


@router.get("/channels", response_model=list[ChannelInfo])
async def list_channels():
    """List all channels with their status and post count."""
    from storage import get_database
    from sqlalchemy import text

    db = get_database()
    async with db.session() as session:
        result = await session.execute(text("""
            SELECT c.id, c.username, c.name, c.is_active, COUNT(p.id) as posts_count
            FROM channels c
            LEFT JOIN posts p ON p.channel_id = c.id
            GROUP BY c.id
            ORDER BY c.username
        """))
        rows = result.fetchall()

        return [
            ChannelInfo(
                id=row.id,
                username=row.username,
                name=row.name,
                is_active=row.is_active,
                posts_count=row.posts_count,
            )
            for row in rows
        ]


@router.patch("/channel/{channel_id}")
async def toggle_channel(channel_id: int, is_active: bool = Query(...)):
    """
    Toggle channel active status.

    - is_active=true: Channel will be included in fetches and ranking
    - is_active=false: Channel excluded from fetches and ranking
    """
    from storage import get_database
    from storage.models import Channel
    from sqlalchemy import update

    db = get_database()
    async with db.session() as session:
        result = await session.execute(
            update(Channel)
            .where(Channel.id == channel_id)
            .values(is_active=is_active)
            .returning(Channel.id, Channel.username, Channel.is_active)
        )
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Channel not found")

        await session.commit()

        return {
            "status": "updated",
            "channel_id": row.id,
            "username": row.username,
            "is_active": row.is_active,
        }


@router.delete("/channel/{channel_id}")
async def delete_channel(channel_id: int):
    """
    Delete a channel and all its posts.

    Warning: This is irreversible!
    """
    from storage import get_database
    from storage.models import Channel, Post, Score
    from sqlalchemy import delete, select

    db = get_database()
    async with db.session() as session:
        # Get channel info first
        channel = await session.get(Channel, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        username = channel.username

        # Delete scores for channel's posts
        post_ids = await session.execute(
            select(Post.id).where(Post.channel_id == channel_id)
        )
        post_id_list = [row[0] for row in post_ids.fetchall()]

        if post_id_list:
            await session.execute(
                delete(Score).where(Score.post_id.in_(post_id_list))
            )

        # Delete posts
        await session.execute(
            delete(Post).where(Post.channel_id == channel_id)
        )

        # Delete channel
        await session.execute(
            delete(Channel).where(Channel.id == channel_id)
        )

        await session.commit()

        return {
            "status": "deleted",
            "channel_id": channel_id,
            "username": username,
        }


@router.post("/import", response_model=BulkImportResponse)
async def bulk_import(request: BulkImportRequest):
    """
    Bulk import channels from a list.

    - Adds all channels to database
    - Triggers collection for all
    - Optionally runs ranking after collection completes
    """
    from storage import get_database, ChannelRepository

    try:
        from jobs.tasks import bulk_import_channels
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Celery tasks not available. Is the worker running?"
        )

    # Normalize and deduplicate channel names
    channels = []
    for ch in request.channels:
        # Clean: remove @, trim, take first word
        clean = ch.replace("@", "").strip().split()[0] if ch.strip() else ""
        if clean and clean not in channels:
            channels.append(clean)

    if not channels:
        raise HTTPException(status_code=400, detail="No valid channels provided")

    # Add all channels to database first
    db = get_database()
    added = 0
    async with db.session() as session:
        repo = ChannelRepository(session)
        for username in channels:
            existing = await repo.get_by_username(username)
            if not existing:
                await repo.upsert(username=username, name=username)
                added += 1
        await session.commit()

    # Trigger bulk import task
    result = bulk_import_channels.delay(
        channels=channels,
        since_days=request.since_days,
        auto_rank=request.auto_rank,
    )

    return BulkImportResponse(
        status="scheduled",
        task_id=str(result.id),
        channels_count=len(channels),
        message=f"Added {added} new channels, scheduled fetch for {len(channels)} channels",
    )


@router.post("/ingest", response_model=IngestResponse)
async def ingest_channels(request: IngestRequest):
    """
    Unified endpoint to ingest (add + collect) one or more channels.

    This endpoint:
    1. Normalizes channel usernames
    2. Upserts channels into database
    3. Triggers ingestion with specified mode (window/incremental/refresh_recent)
    4. Returns task_id for tracking

    Supports both single channel and bulk operations.

    Args:
        channels: List of channel usernames (1 or more)
        mode: Ingestion mode (incremental|refresh_recent|window)
        since_days: Days window (only used for window mode, 1-30 recommended)
        limit: Optional message limit
        auto_rank: Whether to trigger ranking after ingestion (default: false)
    """
    from storage import get_database, ChannelRepository

    try:
        from jobs.tasks import bulk_import_channels, fetch_channel
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Celery tasks not available. Is the worker running?"
        )

    # Validate mode
    valid_modes = ["window", "incremental", "refresh_recent"]
    if request.mode not in valid_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode. Must be one of: {', '.join(valid_modes)}"
        )

    # Validate since_days for window mode
    if request.mode == "window" and not (1 <= request.since_days <= 30):
        raise HTTPException(
            status_code=400,
            detail="since_days must be between 1 and 30 for window mode"
        )

    # Normalize and deduplicate channel names (same logic as bulk_import)
    normalized = []
    for ch in request.channels:
        # Clean: remove @, trim, take first word
        clean = ch.replace("@", "").strip().split()[0] if ch.strip() else ""
        if clean and clean not in normalized:
            normalized.append(clean)

    if not normalized:
        raise HTTPException(status_code=400, detail="No valid channels provided")

    # Upsert all channels to database
    db = get_database()
    added = 0
    async with db.session() as session:
        repo = ChannelRepository(session)
        for username in normalized:
            existing = await repo.get_by_username(username)
            if not existing:
                await repo.upsert(username=username, name=username)
                added += 1
        await session.commit()

    # Trigger ingestion
    #
    # Note: If we schedule a Celery group directly, its id may not be queryable
    # via our /admin/task endpoint (depends on backend). For trackability, prefer
    # a real task id for single-channel ingestion; for multi-channel ingestion,
    # use bulk_import_channels (which returns a summary + group_id).
    if not request.auto_rank and len(normalized) == 1:
        username = normalized[0]
        result = fetch_channel.delay(
            username,
            limit=request.limit,
            since_days=request.since_days,
            mode=request.mode,
        )
    else:
        result = bulk_import_channels.delay(
            channels=normalized,
            since_days=request.since_days,
            auto_rank=request.auto_rank,
            mode=request.mode,
            limit=request.limit,
        )

    return IngestResponse(
        status="scheduled",
        task_id=str(result.id),
        channels_count=len(normalized),
        normalized_channels=normalized,
        message=f"Added {added} new channels, scheduled {request.mode} ingestion for {len(normalized)} channels",
    )


@router.post("/rank")
async def trigger_rank(
    period: str = Query("weekly", pattern="^(daily|weekly|monthly)$"),
    formula: str = Query("v4", pattern="^(v2|v3|v4)$"),
):
    """
    Trigger post ranking.

    - v2: channel-relative + engagement (normalizes across different channel sizes)
    - v3: v2 + novelty bonus (requires novelty_score)
    - v4: v3 + frequency penalty (penalizes spam-heavy channels)

    Note: Requires Celery worker to be running.
    """
    try:
        from jobs.tasks import rank_posts
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Celery tasks not available. Is the worker running?"
        )

    result = rank_posts.delay(period=period, formula=formula)
    return {
        "status": "scheduled",
        "task_id": str(result.id),
        "period": period,
        "formula": formula,
    }


class PipelineRequest(BaseModel):
    """Request to run full update pipeline."""
    since_days: int = 1
    with_novelty: bool = True
    novelty_limit: int = 50
    novelty_analysis_hours: int = 48
    novelty_context_days: int = 14
    allow_large_novelty_backfill: bool = False
    # Formula used to produce a "baseline" score before novelty runs.
    # This improves novelty context selection (it orders context posts by score).
    # v1 is legacy; v2 is the modern engagement baseline.
    context_formula: Literal["v2", "v3", "v4"] = "v2"
    final_formula: Literal["v2", "v3", "v4"] = "v4"
    rank_periods: list[Literal["daily", "weekly", "monthly"]] = ["daily"]
    fetch_mode: Literal["window", "incremental", "refresh_recent"] = "window"
    channels: Optional[list[str]] = None


class PipelineResponse(BaseModel):
    """Response from pipeline operation."""
    status: str
    pipeline_id: str
    with_novelty: bool
    final_formula: str
    message: str


@router.post("/pipeline", response_model=PipelineResponse)
async def trigger_pipeline(request: PipelineRequest):
    """
    Run full update pipeline: fetch → stats → rank (context) → novelty → rank (final).

    Pipeline steps:
    1. Fetch posts from all active channels (since_days)
    2. Update channel stats (for v2/v4 formulas)
    3. Rank posts with context_formula (helps novelty choose better context)
    4. Compute novelty scores for new posts (if with_novelty=true)
    5. Rank posts with final_formula

    Note: Requires Celery worker to be running.
    """
    try:
        from celery import chain, chord, group
        from jobs.tasks import (
            compute_novelty_scores,
            fetch_channel,
            rank_posts,
            update_all_channel_stats,
        )
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Celery tasks not available. Is the worker running?"
        )

    # Validate novelty_analysis_hours (30d backfill is possible but must be explicit).
    if request.novelty_analysis_hours < 1 or request.novelty_analysis_hours > 720:
        raise HTTPException(
            status_code=400,
            detail="novelty_analysis_hours must be between 1 and 720",
        )
    if request.novelty_analysis_hours > 168 and not request.allow_large_novelty_backfill:
        raise HTTPException(
            status_code=400,
            detail="Large novelty backfill (>168h) requires allow_large_novelty_backfill=true",
        )

    # Normalize and validate channels list
    normalized_channels: Optional[list[str]] = None
    if request.channels:
        normalized_channels = []
        for ch in request.channels:
            clean = ch.replace("@", "").strip().split()[0] if ch and ch.strip() else ""
            if clean and clean not in normalized_channels:
                normalized_channels.append(clean)

    # Build callback chain (immutable signatures to ignore fetch results list).
    callback_tasks = [update_all_channel_stats.si(days=30)]  # Required for v2/v4 formulas

    if request.with_novelty:
        # Baseline ranking BEFORE novelty: used by NoveltyAnalyzer.get_context_posts()
        # to order context posts (it takes max Score per post).
        for p in request.rank_periods:
            callback_tasks.append(rank_posts.si(period=p, formula=request.context_formula))

        callback_tasks.append(
            compute_novelty_scores.si(
                limit=request.novelty_limit,
                analysis_hours=request.novelty_analysis_hours,
                context_days=request.novelty_context_days,
                channels=normalized_channels,
            )
        )

    # Final ranking (always).
    for p in request.rank_periods:
        callback_tasks.append(rank_posts.si(period=p, formula=request.final_formula))

    callback = chain(*callback_tasks)

    # Fetch stage MUST wait for per-channel tasks; build a chord (group → callback).
    from storage import get_database, ChannelRepository

    db = get_database()
    async with db.session() as session:
        if normalized_channels:
            channels = [await ChannelRepository(session).get_by_username(u) for u in normalized_channels]
            usernames = [c.username for c in channels if c is not None and c.is_active]
        else:
            channels = await ChannelRepository(session).get_all_active()
            usernames = [c.username for c in channels]

    if not usernames:
        raise HTTPException(status_code=400, detail="No active channels found")

    # Stagger fetches to reduce FloodWait risk.
    fetch_tasks = []
    for i, username in enumerate(usernames):
        fetch_tasks.append(
            fetch_channel.signature(
                args=(username,),
                kwargs={"since_days": request.since_days, "mode": request.fetch_mode},
                countdown=i * 0.3,
            )
        )

    result = chord(group(fetch_tasks), callback).apply_async()

    steps = ["fetch", "stats"]
    if request.with_novelty:
        steps.extend([f"rank_{request.context_formula}:{p}" for p in request.rank_periods])
        steps.append("novelty")
    steps.extend([f"rank_{request.final_formula}:{p}" for p in request.rank_periods])

    return PipelineResponse(
        status="started",
        pipeline_id=str(result.id),
        with_novelty=request.with_novelty,
        final_formula=request.final_formula,
        message=f"Pipeline started: {' → '.join(steps)}",
    )


@router.post("/channel-stats")
async def trigger_channel_stats(
    days: int = Query(30, ge=7, le=90, description="Days of data to analyze"),
):
    """
    Update channel statistics for v2 formula.

    Computes avg_views, avg_forwards, median_engagement for each channel
    based on their posts from the last N days.

    This should be run before using v2/v3 formulas for accurate scoring.
    """
    try:
        from jobs.tasks import update_channel_stats
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Celery tasks not available. Is the worker running?"
        )

    result = update_channel_stats.delay(channel_id=None, days=days)
    return {
        "status": "scheduled",
        "task_id": str(result.id),
        "days": days,
    }


@router.post("/novelty")
async def trigger_novelty(
    limit: int = Query(default=None, ge=1, le=1000, description="Max posts to analyze (None=all in window)"),
    analysis_hours: int = Query(48, ge=1, le=720, description="Hours window for posts to analyze"),
    context_days: int = Query(30, ge=1, le=90, description="Days of context for comparison"),
    force: bool = Query(False, description="Force re-analyze posts that already have scores"),
    allow_large_backfill: bool = Query(False, description="Required for analysis_hours > 168"),
):
    """
    Compute novelty scores for posts.

    Uses LLM (OpenRouter) to analyze information novelty by comparing
    each post against top 300 posts from the last context_days.

    By default analyzes ALL posts in the last 48 hours that don't have a novelty score.
    Use force=true to re-analyze posts that already have scores.

    Note: Requires OPENROUTER_API_KEY and Celery worker.
    """
    try:
        from jobs.tasks import compute_novelty_scores
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Celery tasks not available. Is the worker running?"
        )

    if analysis_hours > 168 and not allow_large_backfill:
        raise HTTPException(
            status_code=400,
            detail="Large novelty backfill (>168h) requires allow_large_backfill=true",
        )

    result = compute_novelty_scores.delay(
        limit=limit,
        analysis_hours=analysis_hours,
        context_days=context_days,
        force=force,
    )
    return {
        "status": "scheduled",
        "task_id": str(result.id),
        "limit": limit,
        "analysis_hours": analysis_hours,
        "context_days": context_days,
        "force": force,
        "allow_large_backfill": allow_large_backfill,
    }


class NoveltyRunRequest(BaseModel):
    """Request to run novelty scoring with optional channel scoping."""

    limit: Optional[int] = None
    analysis_hours: int = 48
    context_days: int = 30
    force: bool = False
    allow_large_backfill: bool = False
    channels: Optional[list[str]] = None


@router.post("/novelty/run")
async def trigger_novelty_run(request: NoveltyRunRequest):
    """
    Compute novelty scores for posts (body-based).

    Supports scoping to a list of channels and larger backfills (up to 30d) with explicit confirmation.
    """
    try:
        from jobs.tasks import compute_novelty_scores
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Celery tasks not available. Is the worker running?"
        )

    if request.analysis_hours < 1 or request.analysis_hours > 720:
        raise HTTPException(status_code=400, detail="analysis_hours must be between 1 and 720")
    if request.analysis_hours > 168 and not request.allow_large_backfill:
        raise HTTPException(
            status_code=400,
            detail="Large novelty backfill (>168h) requires allow_large_backfill=true",
        )

    normalized_channels: Optional[list[str]] = None
    if request.channels:
        normalized_channels = []
        for ch in request.channels:
            clean = ch.replace("@", "").strip().split()[0] if ch and ch.strip() else ""
            if clean and clean not in normalized_channels:
                normalized_channels.append(clean)

    result = compute_novelty_scores.delay(
        limit=request.limit,
        analysis_hours=request.analysis_hours,
        context_days=request.context_days,
        force=request.force,
        channels=normalized_channels,
    )
    return {
        "status": "scheduled",
        "task_id": str(result.id),
        "limit": request.limit,
        "analysis_hours": request.analysis_hours,
        "context_days": request.context_days,
        "force": request.force,
        "allow_large_backfill": request.allow_large_backfill,
        "channels": normalized_channels,
    }


@router.post("/embeddings/backfill")
async def trigger_embeddings_backfill(
    batch_size: int = Query(32, ge=1, le=100, description="Texts per API call"),
    limit: Optional[int] = Query(None, ge=1, le=100000, description="Max posts to process"),
    force: bool = Query(False, description="Re-embed posts that already have embeddings"),
):
    """
    Trigger embedding backfill for semantic search.

    Generates vector embeddings (BGE-M3 via OpenRouter) for posts that
    don't have embeddings yet. Required before hybrid/semantic search works.

    Note: Requires OPENROUTER_API_KEY and Celery worker.
    """
    try:
        from jobs.tasks import backfill_embeddings
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Celery tasks not available. Is the worker running?"
        )

    if not os.environ.get("OPENROUTER_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail="OPENROUTER_API_KEY not configured"
        )

    result = backfill_embeddings.delay(
        batch_size=batch_size,
        limit=limit,
        force=force,
    )
    return {
        "status": "scheduled",
        "task_id": str(result.id),
        "batch_size": batch_size,
        "limit": limit,
        "force": force,
    }


@router.get("/embeddings/status")
async def get_embeddings_status():
    """
    Get embedding coverage statistics.

    Returns count of posts with/without embeddings.
    """
    from storage import get_database
    from sqlalchemy import text

    db = get_database()
    async with db.session() as session:
        result = await session.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM posts WHERE text IS NOT NULL AND length(text) >= 30) AS eligible,
                (SELECT COUNT(*) FROM post_embeddings) AS embedded
        """))
        row = result.fetchone()
        eligible = row.eligible or 0
        embedded = row.embedded or 0

        return {
            "eligible_posts": eligible,
            "embedded_posts": embedded,
            "coverage_pct": round(embedded / eligible * 100, 1) if eligible > 0 else 0,
            "missing": eligible - embedded,
        }


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """Get status of a Celery task."""
    try:
        from jobs.celery_app import celery_app
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Celery not available"
        )

    result = celery_app.AsyncResult(task_id)
    response = {
        "task_id": task_id,
        "status": result.status,
    }

    if result.ready():
        if result.successful():
            response["result"] = result.result
        else:
            response["error"] = str(result.result)

    return response


# =============================================================================
# Settings Management
# =============================================================================

class SettingsResponse(BaseModel):
    """Response with all settings."""
    settings: dict
    defaults: dict


class UpdateSettingsRequest(BaseModel):
    """Request to update settings."""
    settings: dict


class UpdateSettingsResponse(BaseModel):
    """Response from settings update."""
    updated: list[str]
    settings: dict


# Validation rules for settings
SETTINGS_VALIDATION = {
    "ranking.post_limit": {"type": int, "min": 100, "max": 500000},
    "ranking.novelty_weight": {"type": float, "min": 0.0, "max": 20.0},
    "ranking.avg_posts_per_day": {"type": float, "min": 0.1, "max": 100.0},
    "collector.fetch_window_days": {"type": int, "min": 1, "max": 30},
    "collector.deep_fetch_days": {"type": int, "min": 1, "max": 90},
    "collector.incremental_grace_minutes": {"type": int, "min": 0, "max": 180},
    "collector.refresh_recent_hours": {"type": int, "min": 1, "max": 168},
    "novelty.context_days": {"type": int, "min": 1, "max": 90},
    "novelty.batch_limit": {"type": int, "min": 1, "max": 500},
    "automation.ingestion_incremental_enabled": {"type": bool},
    "automation.ingestion_incremental_minutes": {"type": int, "min": 1, "max": 1440},
    "automation.ingestion_refresh_enabled": {"type": bool},
    "automation.ingestion_refresh_minutes": {"type": int, "min": 1, "max": 1440},
    "automation.novelty_enabled": {"type": bool},
    "automation.novelty_minutes": {"type": int, "min": 1, "max": 1440},
    "automation.rank_daily_v4_enabled": {"type": bool},
    "automation.rank_daily_v4_minutes": {"type": int, "min": 1, "max": 1440},
}


def validate_setting(key: str, value) -> tuple[bool, str | None]:
    """Validate a setting value. Returns (is_valid, error_message)."""
    if key not in SETTINGS_VALIDATION:
        return True, None  # Unknown settings pass through

    rules = SETTINGS_VALIDATION[key]
    expected_type = rules["type"]

    # Type check
    if expected_type is bool:
        if isinstance(value, bool):
            pass
        elif isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "y", "on"}:
                value = True
            elif lowered in {"false", "0", "no", "n", "off"}:
                value = False
            else:
                return False, f"{key}: expected boolean"
        elif isinstance(value, int):
            if value in (0, 1):
                value = bool(value)
            else:
                return False, f"{key}: expected boolean (0/1)"
        else:
            return False, f"{key}: expected boolean"
    else:
        try:
            value = expected_type(value)
        except (ValueError, TypeError):
            return False, f"{key}: expected {expected_type.__name__}"

    # Range check
    if "min" in rules and value < rules["min"]:
        return False, f"{key}: minimum is {rules['min']}"
    if "max" in rules and value > rules["max"]:
        return False, f"{key}: maximum is {rules['max']}"

    return True, None


@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """
    Get all application settings.

    Returns current values merged with defaults.
    """
    from core.settings import get_settings_manager, DEFAULTS

    manager = get_settings_manager()
    settings = await manager.get_all()

    return SettingsResponse(
        settings=settings,
        defaults=DEFAULTS,
    )


@router.put("/settings", response_model=UpdateSettingsResponse)
async def update_settings(
    request: UpdateSettingsRequest,
    current_user: User = Depends(get_current_admin),
):
    """
    Update application settings.

    Only updates the provided keys. Validates values before saving.
    """
    from core.settings import get_settings_manager

    # Validate all settings first
    errors = []
    for key, value in request.settings.items():
        is_valid, error = validate_setting(key, value)
        if not is_valid:
            errors.append(error)

    if errors:
        raise HTTPException(
            status_code=400,
            detail={"errors": errors}
        )

    # Get user info for audit
    updated_by = f"user:{current_user.id}" if current_user else "admin"

    # Update settings
    manager = get_settings_manager()
    await manager.set_many(request.settings, updated_by=updated_by)

    # Return updated settings
    settings = await manager.get_all()

    return UpdateSettingsResponse(
        updated=list(request.settings.keys()),
        settings=settings,
    )


@router.get("/settings/{key}")
async def get_setting(key: str):
    """Get a single setting with metadata."""
    from storage import get_database, SettingsRepository
    from core.settings import DEFAULTS

    db = get_database()
    async with db.session() as session:
        repo = SettingsRepository(session)
        setting = await repo.get_setting_object(key)

        if setting:
            return {
                "key": key,
                "value": setting.value,
                "description": setting.description,
                "updated_at": setting.updated_at.isoformat() if setting.updated_at else None,
                "updated_by": setting.updated_by,
                "is_default": False,
            }

        # Check if it's a known default
        if key in DEFAULTS:
            return {
                "key": key,
                "value": DEFAULTS[key],
                "description": None,
                "updated_at": None,
                "updated_by": None,
                "is_default": True,
            }

        raise HTTPException(status_code=404, detail=f"Setting not found: {key}")


# =============================================================================
# Task Profiling
# =============================================================================

class TaskRunInfo(BaseModel):
    """Task run information."""
    id: int
    task_name: str
    started_at: Optional[str]
    finished_at: Optional[str]
    duration_ms: Optional[int]
    status: str
    input_params: Optional[dict]
    result_summary: Optional[dict]
    error_message: Optional[str]


class ProfilingResponse(BaseModel):
    """Response with task runs."""
    runs: list[TaskRunInfo]
    total: int


class ProfilingStatsResponse(BaseModel):
    """Response with profiling statistics."""
    by_task: dict
    total_runs: int
    days: int


@router.get("/profiling", response_model=ProfilingResponse)
async def get_profiling(
    limit: int = Query(50, ge=1, le=500),
    task_name: Optional[str] = None,
):
    """
    Get recent task runs.

    Args:
        limit: Maximum number of runs to return
        task_name: Optional filter by task name
    """
    from core.profiler import get_recent_runs

    runs = await get_recent_runs(limit=limit, task_name=task_name)

    return ProfilingResponse(
        runs=[TaskRunInfo(**run) for run in runs],
        total=len(runs),
    )


@router.get("/profiling/stats", response_model=ProfilingStatsResponse)
async def get_profiling_stats(
    days: int = Query(7, ge=1, le=90),
    task_name: Optional[str] = None,
):
    """
    Get aggregated profiling statistics.

    Returns average duration, success rate, etc. per task.
    """
    from core.profiler import get_profiling_stats as _get_stats

    stats = await _get_stats(days=days, task_name=task_name)

    return ProfilingStatsResponse(**stats)


@router.delete("/profiling/cleanup")
async def cleanup_profiling(
    days: int = Query(30, ge=7, le=365),
):
    """
    Delete old task runs.

    Args:
        days: Delete runs older than this many days
    """
    from core.profiler import cleanup_old_runs

    deleted = await cleanup_old_runs(days=days)

    return {
        "status": "ok",
        "deleted": deleted,
        "older_than_days": days,
    }
