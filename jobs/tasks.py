"""Celery tasks for fetching and ranking Telegram posts."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Literal, Optional

from celery import group
from dotenv import load_dotenv

from jobs.celery_app import celery_app
from jobs.locks import redis_lock
from core.profiler import profile_task

load_dotenv()

logger = logging.getLogger(__name__)

# Rate limit for Telegram API (configurable via env)
TELEGRAM_RATE_LIMIT = os.getenv("TELEGRAM_RATE_LIMIT", "20/s")


def run_async(coro):
    """Run async coroutine in sync context."""
    return asyncio.run(coro)


@celery_app.task(
    bind=True,
    retry_kwargs={"max_retries": 5},
    rate_limit=TELEGRAM_RATE_LIMIT,
)
@profile_task
def fetch_channel(
    self,
    channel_username: str,
    limit: Optional[int] = None,
    since_days: Optional[int] = 7,
    mode: Literal["window", "incremental", "refresh_recent"] = "window",
) -> dict:
    """
    Fetch posts from a single Telegram channel and save to database.

    Args:
        channel_username: Channel username (with or without @)
        limit: Max messages to fetch (None for no limit)
        since_days: Fetch messages from last N days (default: 7)
        mode:
          - window: fetch last N days window (manual/backfill)
          - incremental: fetch only new posts since last_fetched_at (scheduled)
          - refresh_recent: re-fetch last N hours to update metrics

    Returns:
        dict with status and count of imported posts
    """
    async def _fetch():
        from collector.fetch import fetch_messages
        from collector.errors import FetchPermanentError, FetchTransientError
        from core.settings import DEFAULTS
        from storage import Database, PostRepository, ChannelRepository, SettingsRepository

        # Normalize username to match API/frontend behavior
        normalized = channel_username.replace("@", "").strip().split()[0] if channel_username.strip() else ""
        if not normalized:
            raise FetchPermanentError("Invalid channel username")

        now = datetime.now(timezone.utc).replace(microsecond=0)

        # Compute fetch window bounds
        db = Database()
        try:
            async with db.session() as session:
                settings_repo = SettingsRepository(session)
                grace_minutes = int(
                    (await settings_repo.get("collector.incremental_grace_minutes"))
                    or DEFAULTS["collector.incremental_grace_minutes"]
                )
                refresh_hours = int(
                    (await settings_repo.get("collector.refresh_recent_hours"))
                    or DEFAULTS["collector.refresh_recent_hours"]
                )

                # Ensure channel exists and read last_fetched_at
                channel_repo = ChannelRepository(session)
                channel = await channel_repo.get_by_username(normalized)
                if channel is None:
                    channel = await channel_repo.upsert(username=normalized, name=normalized)
                    await session.commit()

                last_fetched_at = channel.last_fetched_at
        finally:
            await db.close()

        since: datetime | None
        if mode == "incremental":
            if last_fetched_at is None:
                # First run: fall back to a small window (default: since_days)
                from datetime import timedelta
                window_days = since_days or 1
                since = now - timedelta(days=window_days)
            else:
                from datetime import timedelta
                since = last_fetched_at - timedelta(minutes=grace_minutes)
        elif mode == "refresh_recent":
            from datetime import timedelta
            since = now - timedelta(hours=refresh_hours)
        else:
            # window mode (legacy/manual): start at midnight UTC N days ago
            if since_days:
                from datetime import timedelta
                since = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=since_days)
            else:
                since = None

        lock_key = f"fetch:{normalized}:{mode}"
        with redis_lock(lock_key, ttl_seconds=600, blocking=False) as acquired:
            if not acquired:
                logger.info(f"Skip fetch @{normalized} (lock busy): {lock_key}")
                return {"status": "skipped", "channel": normalized, "count": 0, "mode": mode}

            # Fetch from Telegram
            logger.info(f"Fetching @{normalized} mode={mode} since={since.isoformat() if since else None}")
            try:
                messages = await fetch_messages(f"@{normalized}", limit=limit, since=since)
            except FetchPermanentError as e:
                # Disable channel to stop repeated scheduled failures (manual re-enable in admin UI).
                try:
                    from sqlalchemy import update
                    from storage.models import Channel

                    db = Database()
                    try:
                        async with db.session() as session:
                            await session.execute(
                                update(Channel)
                                .where(Channel.username == normalized)
                                .values(is_active=False)
                            )
                            await session.commit()
                    finally:
                        await db.close()
                except Exception:
                    pass
                return {
                    "status": "error",
                    "channel": normalized,
                    "count": 0,
                    "mode": mode,
                    "error": str(e),
                    "reason": getattr(e, "reason", None),
                    "disabled": True,
                }
            except FetchTransientError as e:
                raise

            logger.info(f"Fetched {len(messages)} messages from @{normalized}")

        # Basic telemetry on fetched batch (for task_runs profiling summary)
        null_text_count = 0
        min_date = None
        max_date = None
        for m in messages:
            if m.get("text") is None:
                null_text_count += 1
            dt = m.get("date")
            if isinstance(dt, str):
                try:
                    dt = datetime.fromisoformat(dt)
                except Exception:
                    dt = None
            if isinstance(dt, datetime):
                min_date = dt if min_date is None else min(min_date, dt)
                max_date = dt if max_date is None else max(max_date, dt)

        # Save to database
        db = Database()
        try:
            async with db.session() as session:
                repo = PostRepository(session)
                count = await repo.upsert_from_collector(normalized, messages)
                await session.commit()
                logger.info(f"Saved {count} posts from @{normalized}")
                return {
                    "status": "ok",
                    "channel": normalized,
                    "count": count,
                    "fetched": len(messages),
                    "mode": mode,
                    "since": since.isoformat() if since else None,
                    "null_text": null_text_count,
                    "min_date": min_date.isoformat() if min_date else None,
                    "max_date": max_date.isoformat() if max_date else None,
                }
        finally:
            await db.close()

    try:
        return run_async(_fetch())
    except Exception as e:
        from collector.errors import FetchTransientError

        if isinstance(e, FetchTransientError):
            # If Telegram asked for a specific wait time - respect it. Otherwise apply exponential backoff.
            if e.retry_after:
                countdown = e.retry_after
            else:
                countdown = min(30 * (2 ** getattr(self.request, "retries", 0)), 600)
            try:
                raise self.retry(exc=e, countdown=countdown)
            except Exception as retry_exc:
                # If retries are exhausted, do not fail the whole pipeline/chord.
                # Return an error payload so downstream tasks can still run.
                try:
                    from celery.exceptions import MaxRetriesExceededError
                except Exception:
                    MaxRetriesExceededError = None  # type: ignore

                if MaxRetriesExceededError is not None and isinstance(retry_exc, MaxRetriesExceededError):
                    normalized = channel_username.replace("@", "").strip().split()[0] if channel_username.strip() else ""
                    return {
                        "status": "error",
                        "channel": normalized or channel_username,
                        "count": 0,
                        "mode": mode,
                        "error": str(e),
                        "reason": "transient_max_retries",
                        "disabled": False,
                    }
                raise
        raise


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
@profile_task
def rank_posts(
    self,
    period: str = "weekly",
    formula: str = "v4",
) -> dict:
    """
    Rank posts for a given period and save scores to database.

    Args:
        period: Period type (daily, weekly, monthly)
        formula: Scoring formula version (v2, v3, v4)

    Returns:
        dict with status and count of scored posts
    """
    async def _rank():
        from sqlalchemy import select, func
        from ranker import Scorer, Period
        from ranker.locking import RankingLock
        from ranker.periods import get_bucketed_period_bounds
        from storage import Database
        from storage.models import Channel

        # Map string to Period enum
        period_map = {
            "daily": Period.DAILY,
            "weekly": Period.WEEKLY,
            "monthly": Period.MONTHLY,
            "all": Period.ALL,
        }
        period_enum = period_map.get(period, Period.WEEKLY)

        # Get period bucket end for precise locking
        _, period_end = get_bucketed_period_bounds(period_enum)
        period_bucket_iso = period_end.isoformat()

        # Acquire distributed lock to prevent overlapping ranking tasks
        # Create fresh lock instance per task (avoid singleton event loop issues)
        lock = RankingLock()
        try:
            async with lock.acquire(
                formula=formula,
                period=period,
                period_bucket_end=period_bucket_iso,
                timeout=300,  # 5 minutes max per ranking task
            ) as acquired:
                if not acquired:
                    logger.warning(
                        f"Could not acquire lock for {formula}/{period}/{period_bucket_iso}. "
                        f"Another task may be running."
                    )
                    return {
                        "status": "skipped",
                        "reason": "lock_not_acquired",
                        "period": period,
                        "formula": formula,
                    }

                db = Database()
                try:
                    async with db.session() as session:
                        # Calculate global average posts per day for v4 formula
                        global_avg_posts_per_day = None
                        if formula == "v4":
                            avg_query = select(func.avg(Channel.posts_per_day_30d)).where(
                                Channel.is_active == True,  # noqa: E712
                                Channel.posts_per_day_30d != None,  # noqa: E711
                                Channel.posts_per_day_30d > 0,
                            )
                            result = await session.execute(avg_query)
                            global_avg_posts_per_day = result.scalar()
                            if global_avg_posts_per_day:
                                logger.info(f"Global avg posts/day: {global_avg_posts_per_day:.2f}")

                        # Create scorer with period for adaptive decay
                        scorer = Scorer(
                            session,
                            formula,
                            global_avg_posts_per_day=global_avg_posts_per_day,
                            period=period_enum,  # Enable period-aware decay rates
                        )

                        # Rank and save with bucketed boundaries (default: use_bucketed_bounds=True)
                        scores, saved = await scorer.rank_and_save_by_period_type(period_enum)
                        await session.commit()

                        logger.info(
                            f"Ranked {saved} posts for {period} with {formula} "
                            f"(adaptive decay enabled)"
                        )
                        return {
                            "status": "ok",
                            "period": period,
                            "formula": formula,
                            "count": saved,
                            "global_avg_posts_per_day": global_avg_posts_per_day,
                        }
                finally:
                    await db.close()
        finally:
            await lock.close()

    return run_async(_rank())


@celery_app.task(bind=True)
@profile_task
def fetch_all_channels(
    self,
    limit: Optional[int] = None,
    since_days: int = 7,
    stagger_seconds: float = 0.5,
    mode: Literal["window", "incremental", "refresh_recent"] = "window",
) -> dict:
    """
    Fetch posts from all active channels in database.

    This task creates a group of fetch_channel tasks with staggered
    execution to respect Telegram rate limits.

    Args:
        limit: Max messages per channel
        since_days: Fetch messages from last N days
        stagger_seconds: Delay between channel fetches for rate limiting
        mode: window/incremental/refresh_recent (see fetch_channel)

    Returns:
        dict with status and list of channel usernames
    """
    async def _get_channels():
        from storage import Database, ChannelRepository

        db = Database()
        try:
            async with db.session() as session:
                repo = ChannelRepository(session)
                channels = await repo.get_all_active()
                return [ch.username for ch in channels]
        finally:
            await db.close()

    channels = run_async(_get_channels())

    if not channels:
        logger.warning("No active channels found")
        return {"status": "ok", "channels": [], "count": 0}

    # Create tasks with countdown for staggered execution
    tasks = []
    for i, username in enumerate(channels):
        countdown = i * stagger_seconds  # Stagger by 0.5s each
        tasks.append(
            fetch_channel.signature(
                args=(username,),
                kwargs={"limit": limit, "since_days": since_days, "mode": mode},
                countdown=countdown,
            )
        )

    # Execute as a group (parallel with staggered start)
    job = group(tasks)
    result = job.apply_async()

    logger.info(f"Scheduled {len(channels)} channel fetch tasks")
    return {
        "status": "scheduled",
        "channels": channels,
        "count": len(channels),
        "group_id": str(result.id),
        "mode": mode,
    }


@celery_app.task(bind=True)
@profile_task
def full_pipeline(
    self,
    since_days: int = 1,
    with_novelty: bool = True,
    novelty_limit: int = 50,
    novelty_context_days: int = 14,
    final_formula: str = "v4",
) -> dict:
    """
    Run full update pipeline: fetch → stats → novelty → rank v4.

    Pipeline:
    1. Fetch all active channels
    2. Update channel stats (for v2/v4 formulas)
    3. Compute novelty scores for new posts
    4. Rank posts with final formula (v4)

    Args:
        since_days: Fetch messages from last N days
        with_novelty: Whether to compute novelty scores
        novelty_limit: Max posts to analyze for novelty
        novelty_context_days: Days of posts to analyze for novelty
        final_formula: Final ranking formula (v3 or v4, default v4)

    Returns:
        dict with pipeline status
    """
    from celery import chain

    tasks = [
        fetch_all_channels.s(since_days=since_days),
        update_all_channel_stats.si(days=30),
    ]

    if with_novelty:
        tasks.append(compute_novelty_scores.si(limit=novelty_limit, context_days=novelty_context_days))

    tasks.append(rank_posts.si(period="daily", formula=final_formula))

    pipeline = chain(*tasks)
    result = pipeline.apply_async()
    logger.info(f"Started full pipeline: {result.id}")

    return {
        "status": "started",
        "pipeline_id": str(result.id),
        "with_novelty": with_novelty,
        "final_formula": final_formula,
    }


@celery_app.task(bind=True)
@profile_task
def bulk_import_channels(
    self,
    channels: list[str],
    since_days: int = 7,
    auto_rank: bool = True,
    mode: Literal["window", "incremental", "refresh_recent"] = "window",
    limit: Optional[int] = None,
    stagger_seconds: float = 1.0,
) -> dict:
    """
    Bulk import and collect posts from a list of channels.

    This task:
    1. Fetches posts from all specified channels (with staggered execution)
    2. Waits for all fetches to complete
    3. Optionally runs ranking

    Args:
        channels: List of channel usernames
        since_days: Fetch messages from last N days
        auto_rank: Whether to run ranking after collection
        mode: window/incremental/refresh_recent (see fetch_channel)
        limit: Optional message limit per channel
        stagger_seconds: Delay between channel fetches

    Returns:
        dict with import status and results
    """
    from celery import chord

    if not channels:
        return {"status": "error", "message": "No channels provided"}

    logger.info(f"Starting bulk import for {len(channels)} channels")

    # Create fetch tasks with staggered execution
    fetch_tasks = []
    for i, username in enumerate(channels):
        countdown = i * stagger_seconds
        fetch_tasks.append(
            fetch_channel.signature(
                args=(username,),
                kwargs={"since_days": since_days, "mode": mode, "limit": limit},
                countdown=countdown,
            )
        )

    if auto_rank:
        # Use chord: run all fetches, then rank
        callback = rank_posts.si(period="weekly", formula="v4")
        job = chord(fetch_tasks, callback)
        result = job.apply_async()
        logger.info(f"Bulk import with ranking: {result.id}")
    else:
        # Just run fetches as a group
        job = group(fetch_tasks)
        result = job.apply_async()
        logger.info(f"Bulk import without ranking: {result.id}")

    return {
        "status": "scheduled",
        "channels": channels,
        "count": len(channels),
        "auto_rank": auto_rank,
        "group_id": str(result.id),
    }


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
@profile_task
def compute_novelty_scores(
    self,
    limit: Optional[int] = None,
    analysis_hours: int = 48,
    context_days: int = 30,
    force: bool = False,
    channels: Optional[list[str]] = None,
) -> dict:
    """
    Compute novelty scores for posts using LLM.

    This task:
    1. Finds posts in the last analysis_hours (default 48h)
    2. Loads context posts from last context_days for comparison
    3. Calls OpenRouter LLM to analyze novelty
    4. Saves results to database

    Args:
        limit: Max posts to process (None for all in window)
        analysis_hours: Hours window for posts to analyze (default: 48)
        context_days: Days of posts to use as context for comparison
        force: If True, re-analyze posts that already have scores
        channels: Optional list of channel usernames to scope analysis to

    Returns:
        dict with status and counts
    """
    async def _compute():
        from core.settings import load_settings_for_celery, NOVELTY_CRITERIA
        from novelty import NoveltyAnalyzer
        from storage import Database

        # Load settings without singleton (avoid event loop issues)
        settings = await load_settings_for_celery()

        # Extract criteria weights from settings
        criteria_weights = {
            criterion: float(settings.get(f"novelty.weight.{criterion}", 1.0))
            for criterion in NOVELTY_CRITERIA
        }

        db = Database()
        try:
            async with db.session() as session:
                analyzer = NoveltyAnalyzer(
                    session=session,
                    analysis_hours=analysis_hours,
                    context_days=context_days,
                    channel_usernames=channels,
                    criteria_weights=criteria_weights,
                )
                try:
                    analyzed, saved = await analyzer.analyze_and_save(limit=limit, force=force)
                    await session.commit()

                    logger.info(f"Novelty scoring: analyzed={analyzed}, saved={saved}")
                    return {
                        "status": "ok",
                        "analyzed": analyzed,
                        "saved": saved,
                        "analysis_hours": analysis_hours,
                    }
                finally:
                    await analyzer.close()
        finally:
            await db.close()

    return run_async(_compute())


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
@profile_task
def update_channel_stats(
    self,
    channel_id: Optional[int] = None,
    days: int = 30,
) -> dict:
    """
    Update channel statistics for relative scoring (v2/v4 formula).

    Computes:
    - avg_views_30d: Average views per post
    - avg_forwards_30d: Average forwards per post
    - median_engagement_rate: Median (forwards + reactions + replies) / views
    - posts_count_30d: Number of posts analyzed
    - posts_per_day_30d: Posting frequency (v4: frequency penalty)

    Args:
        channel_id: Specific channel to update (None = all active channels)
        days: Number of days to analyze (default: 30)

    Returns:
        dict with status and count of updated channels
    """
    async def _update():
        from datetime import timedelta
        from sqlalchemy import select, func
        from storage import Database
        from storage.models import Channel, Post

        db = Database()
        try:
            async with db.session() as session:
                since = datetime.now(timezone.utc) - timedelta(days=days)

                # Get channels to update
                if channel_id:
                    channels_query = select(Channel).where(Channel.id == channel_id)
                else:
                    channels_query = select(Channel).where(Channel.is_active == True)

                result = await session.execute(channels_query)
                channels = list(result.scalars().all())

                updated = 0
                for channel in channels:
                    # Get posts for this channel
                    posts_query = (
                        select(
                            Post.views,
                            Post.forwards,
                            Post.reactions_count,
                            Post.replies,
                        )
                        .where(Post.channel_id == channel.id)
                        .where(Post.posted_at >= since)
                        .where(Post.views != None)  # noqa: E711
                        .where(Post.views > 0)
                    )
                    posts_result = await session.execute(posts_query)
                    posts_data = posts_result.fetchall()

                    if not posts_data:
                        continue

                    # Calculate statistics
                    views_list = [p.views for p in posts_data]
                    forwards_list = [p.forwards or 0 for p in posts_data]

                    # Engagement rates
                    engagement_rates = []
                    for p in posts_data:
                        views = p.views or 1
                        engagement = (p.forwards or 0) + (p.reactions_count or 0) + (p.replies or 0)
                        engagement_rates.append(engagement / views)

                    # Sort for median
                    engagement_rates.sort()
                    mid = len(engagement_rates) // 2
                    if len(engagement_rates) % 2 == 0:
                        median_engagement = (engagement_rates[mid - 1] + engagement_rates[mid]) / 2
                    else:
                        median_engagement = engagement_rates[mid]

                    # Update channel
                    channel.avg_views_30d = sum(views_list) / len(views_list)
                    channel.avg_forwards_30d = sum(forwards_list) / len(forwards_list)
                    channel.median_engagement_rate = median_engagement
                    channel.posts_count_30d = len(posts_data)
                    channel.posts_per_day_30d = len(posts_data) / days  # v4: frequency penalty
                    channel.stats_updated_at = datetime.now(timezone.utc)

                    updated += 1
                    logger.info(
                        f"Updated stats for @{channel.username}: "
                        f"avg_views={channel.avg_views_30d:.0f}, "
                        f"avg_forwards={channel.avg_forwards_30d:.1f}, "
                        f"engagement={channel.median_engagement_rate:.4f}, "
                        f"posts_per_day={channel.posts_per_day_30d:.2f}"
                    )

                await session.commit()
                return {"status": "ok", "updated": updated}

        finally:
            await db.close()

    return run_async(_update())


@celery_app.task(bind=True)
@profile_task
def update_all_channel_stats(self, days: int = 30) -> dict:
    """
    Update statistics for all active channels.

    Wrapper that calls update_channel_stats for each channel.
    """
    result = update_channel_stats(channel_id=None, days=days)
    return result


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
@profile_task
def backfill_embeddings(
    self,
    batch_size: int = 32,
    limit: Optional[int] = None,
    force: bool = False,
) -> dict:
    """
    Backfill embeddings for posts that don't have them yet.

    Fetches posts without embeddings (or all if force=True),
    generates embeddings via OpenRouter BGE-M3, and upserts
    into post_embeddings table.

    Args:
        batch_size: Number of texts to embed per API call
        limit: Max posts to process (None for all)
        force: If True, re-embed posts even if they already have embeddings

    Returns:
        dict with status and counts
    """
    async def _backfill():
        from sqlalchemy import select, func
        from sqlalchemy.dialects.postgresql import insert

        from storage import Database
        from storage.models import Post, PostEmbedding
        from storage.embedding_client import EmbeddingClient, EmbeddingError
        from storage.text_preprocessor import TextPreprocessor

        min_text_length = 30

        db = Database()
        try:
            async with EmbeddingClient() as client:
                async with db.session() as session:
                    # Find posts without embeddings (or all if force)
                    stmt = (
                        select(Post.id, Post.text)
                        .where(Post.text != None)  # noqa: E711
                        .where(func.length(Post.text) >= min_text_length)
                    )

                    if not force:
                        # Exclude posts that already have embeddings
                        existing = select(PostEmbedding.post_id)
                        stmt = stmt.where(Post.id.notin_(existing))

                    stmt = stmt.order_by(Post.posted_at.desc())

                    if limit:
                        stmt = stmt.limit(limit)

                    rows = (await session.execute(stmt)).all()

                    if not rows:
                        return {"status": "ok", "processed": 0, "embedded": 0, "skipped": 0}

                    processed = 0
                    embedded = 0
                    skipped = 0
                    errors = 0

                    # Process in batches
                    for i in range(0, len(rows), batch_size):
                        batch = rows[i : i + batch_size]

                        # Clean texts
                        cleaned = []
                        valid_posts = []
                        for post_id, text in batch:
                            clean = TextPreprocessor.clean_for_embedding(text)
                            if clean and len(clean) >= min_text_length:
                                cleaned.append(clean)
                                valid_posts.append((post_id, text))
                            else:
                                skipped += 1

                        if not cleaned:
                            continue

                        try:
                            vectors = await client.embed_batch(cleaned)
                        except EmbeddingError as e:
                            logger.error(f"Embedding batch error: {e}")
                            errors += len(cleaned)
                            continue

                        # Upsert embeddings
                        for (post_id, text), vector in zip(valid_posts, vectors):
                            text_hash = EmbeddingClient.compute_text_hash(text)
                            ins = insert(PostEmbedding).values(
                                post_id=post_id,
                                model=client.model,
                                embedding=vector,
                                text_hash=text_hash,
                            )
                            ins = ins.on_conflict_do_update(
                                index_elements=["post_id"],
                                set_={
                                    "embedding": ins.excluded.embedding,
                                    "text_hash": ins.excluded.text_hash,
                                    "model": ins.excluded.model,
                                    "created_at": func.now(),
                                },
                            )
                            await session.execute(ins)
                            embedded += 1

                        await session.commit()
                        processed += len(batch)
                        logger.info(
                            f"Embedding backfill: batch {i // batch_size + 1}, "
                            f"embedded={embedded}, skipped={skipped}"
                        )

                    return {
                        "status": "ok",
                        "processed": processed,
                        "embedded": embedded,
                        "skipped": skipped,
                        "errors": errors,
                        "total_candidates": len(rows),
                    }
        finally:
            await db.close()

    return run_async(_backfill())


@celery_app.task(bind=True)
@profile_task
def automation_tick(self) -> dict:
    """
    Dynamic automation tick (runs frequently, schedules real work when due).

    This task is intended to replace hardcoded Celery Beat intervals so they can
    be controlled via DB-backed settings from the admin UI.
    """

    async def _tick():
        import os
        import time

        from core.settings import load_settings_for_celery

        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            return {"status": "noop", "reason": "REDIS_URL not set", "triggered": []}

        try:
            import redis  # type: ignore
        except Exception:
            return {"status": "noop", "reason": "redis package missing", "triggered": []}

        client = redis.Redis.from_url(redis_url)
        now = int(time.time())

        settings = await load_settings_for_celery()

        def as_bool(v: object, default: bool = False) -> bool:
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() in {"true", "1", "yes", "y", "on"}
            if isinstance(v, int):
                return v == 1
            return default

        def as_int(v: object, default: int) -> int:
            try:
                return int(v)  # type: ignore[arg-type]
            except Exception:
                return default

        triggered: list[str] = []

        def maybe_trigger(job: str, enabled: bool, interval_minutes: int, trigger_fn) -> None:
            if not enabled or interval_minutes <= 0:
                return

            lock = client.lock(
                name=f"automation:lock:{job}",
                timeout=55,
                blocking_timeout=0,
            )
            acquired = lock.acquire(blocking=False)
            if not acquired:
                return

            try:
                last_raw = client.get(f"automation:last:{job}")
                last = int(last_raw) if last_raw else 0
                if last and (now - last) < interval_minutes * 60:
                    return

                client.set(f"automation:last:{job}", str(now))
                trigger_fn()
                triggered.append(job)
            finally:
                try:
                    lock.release()
                except Exception:
                    pass

        # Ingestion: incremental
        maybe_trigger(
            "ingestion_incremental",
            as_bool(settings.get("automation.ingestion_incremental_enabled", True), True),
            as_int(settings.get("automation.ingestion_incremental_minutes", 5), 5),
            lambda: fetch_all_channels.delay(since_days=1, mode="incremental", stagger_seconds=0.3),
        )

        # Ingestion: refresh recent
        maybe_trigger(
            "ingestion_refresh",
            as_bool(settings.get("automation.ingestion_refresh_enabled", True), True),
            as_int(settings.get("automation.ingestion_refresh_minutes", 60), 60),
            lambda: fetch_all_channels.delay(mode="refresh_recent", stagger_seconds=0.6),
        )

        # Novelty (recent window only; backfill is manual)
        novelty_limit = as_int(settings.get("novelty.batch_limit", 20), 20)
        novelty_context_days = as_int(settings.get("novelty.context_days", 30), 30)
        maybe_trigger(
            "novelty",
            as_bool(settings.get("automation.novelty_enabled", True), True),
            as_int(settings.get("automation.novelty_minutes", 5), 5),
            lambda: compute_novelty_scores.delay(
                limit=novelty_limit,
                analysis_hours=48,
                context_days=novelty_context_days,
                force=False,
            ),
        )

        # Rank v4 daily (feeds "day")
        maybe_trigger(
            "rank_daily_v4",
            as_bool(settings.get("automation.rank_daily_v4_enabled", True), True),
            as_int(settings.get("automation.rank_daily_v4_minutes", 5), 5),
            lambda: rank_posts.delay(period="daily", formula="v4"),
        )

        # Embeddings backfill (new posts without embeddings)
        embeddings_batch = as_int(settings.get("search.embedding_batch_size", 32), 32)
        maybe_trigger(
            "embeddings_backfill",
            as_bool(settings.get("automation.embeddings_enabled", True), True),
            as_int(settings.get("automation.embeddings_minutes", 60), 60),
            lambda: backfill_embeddings.delay(batch_size=embeddings_batch, limit=200),
        )

        return {"status": "ok", "triggered": triggered}

    return run_async(_tick())
