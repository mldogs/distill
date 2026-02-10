"""Tests for /feed filters and sorting."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from ranker.periods import Period, PeriodMode, compute_period_hash, get_bucketed_period_bounds
from storage import get_database
from storage.models import Channel, Post
from storage.repositories import ChannelRepository, PostRepository, ScoreRepository


async def seed_channel_with_posts(
    username: str,
    posts_data: list[dict],
) -> list[Post]:
    """Create a channel and upsert posts, returning stored Post rows."""
    db = get_database()
    async with db.session() as session:
        channel = await ChannelRepository(session).upsert(username=username, name=username)
        await PostRepository(session).upsert_posts(channel.id, posts_data)
        result = await session.execute(select(Post).where(Post.channel_id == channel.id))
        return list(result.scalars().all())


async def cleanup_channel(username: str) -> None:
    """Delete a channel by username, cascading to posts/scores/votes."""
    db = get_database()
    async with db.session() as session:
        await session.execute(delete(Channel).where(Channel.username == username))


async def set_novelty_scores(permalink_to_score: dict[str, float | None]) -> None:
    """Update novelty_score for posts by permalink."""
    db = get_database()
    async with db.session() as session:
        for permalink, score in permalink_to_score.items():
            post = await session.scalar(select(Post).where(Post.permalink == permalink))
            assert post is not None
            post.novelty_score = score


@pytest.mark.asyncio
async def test_feed_sort_by_views_desc(client: AsyncClient):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _, period_end = get_bucketed_period_bounds(Period.DAILY, reference=now, mode=PeriodMode.ROLLING)
    username = "sort_views"
    try:
        posts = await seed_channel_with_posts(
            username,
            [
                {
                    "telegram_message_id": 1,
                    "text": "a",
                    "permalink": "https://t.me/sort_views/1",
                    "posted_at": period_end - timedelta(hours=1),
                    "views": 10,
                    "replies": 1,
                    "reactions_count": 2,
                },
                {
                    "telegram_message_id": 2,
                    "text": "b",
                    "permalink": "https://t.me/sort_views/2",
                    "posted_at": period_end - timedelta(hours=2),
                    "views": 30,
                    "replies": 2,
                    "reactions_count": 3,
                },
                {
                    "telegram_message_id": 3,
                    "text": "c",
                    "permalink": "https://t.me/sort_views/3",
                    "posted_at": period_end - timedelta(hours=3),
                    "views": 20,
                    "replies": 3,
                    "reactions_count": 4,
                },
            ],
        )
        assert len(posts) == 3

        resp = await client.get("/feed?period=daily&formula=v2&channel=sort_views&sort_by=views&sort_dir=desc&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        got = [p["views"] for p in data["posts"]]
        assert got == [30, 20, 10]
    finally:
        await cleanup_channel(username)


@pytest.mark.asyncio
async def test_feed_filters_multiple_criteria(client: AsyncClient):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _, period_end = get_bucketed_period_bounds(Period.DAILY, reference=now, mode=PeriodMode.ROLLING)
    username = "multi_filters"
    try:
        await seed_channel_with_posts(
            username,
            [
                {
                    "telegram_message_id": 1,
                    "text": "low replies",
                    "permalink": "https://t.me/multi_filters/1",
                    "posted_at": period_end - timedelta(hours=1),
                    "views": 200,
                    "replies": 0,
                    "reactions_count": 50,
                },
                {
                    "telegram_message_id": 2,
                    "text": "ok",
                    "permalink": "https://t.me/multi_filters/2",
                    "posted_at": period_end - timedelta(hours=2),
                    "views": 150,
                    "replies": 5,
                    "reactions_count": 10,
                },
                {
                    "telegram_message_id": 3,
                    "text": "low views",
                    "permalink": "https://t.me/multi_filters/3",
                    "posted_at": period_end - timedelta(hours=3),
                    "views": 50,
                    "replies": 10,
                    "reactions_count": 100,
                },
            ],
        )

        resp = await client.get("/feed?period=daily&formula=v2&channel=multi_filters&min_views=100&min_replies=5&limit=50")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["posts"]) == 1
        assert data["posts"][0]["permalink"] == "https://t.me/multi_filters/2"
    finally:
        await cleanup_channel(username)


@pytest.mark.asyncio
async def test_feed_dedup_grouped_id_keeps_first_in_sort(client: AsyncClient):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _, period_end = get_bucketed_period_bounds(Period.DAILY, reference=now, mode=PeriodMode.ROLLING)
    username = "dedup_album"
    try:
        await seed_channel_with_posts(
            username,
            [
                {
                    "telegram_message_id": 1,
                    "text": "album low",
                    "permalink": "https://t.me/dedup_album/1",
                    "posted_at": period_end - timedelta(hours=1),
                    "views": 100,
                    "replies": 1,
                    "reactions_count": 1,
                    "grouped_id": 777,
                },
                {
                    "telegram_message_id": 2,
                    "text": "album high",
                    "permalink": "https://t.me/dedup_album/2",
                    "posted_at": period_end - timedelta(hours=2),
                    "views": 200,
                    "replies": 2,
                    "reactions_count": 2,
                    "grouped_id": 777,
                },
                {
                    "telegram_message_id": 3,
                    "text": "other",
                    "permalink": "https://t.me/dedup_album/3",
                    "posted_at": period_end - timedelta(hours=3),
                    "views": 150,
                    "replies": 3,
                    "reactions_count": 3,
                },
            ],
        )

        resp = await client.get("/feed?period=daily&formula=v2&channel=dedup_album&sort_by=views&sort_dir=desc&limit=50")
        assert resp.status_code == 200
        data = resp.json()
        got_views = [p["views"] for p in data["posts"]]

        # Two album posts share grouped_id, so one must be removed.
        assert len(got_views) == 2
        # Sorted by views desc; the kept album post should be the 200-views one.
        assert got_views == [200, 150]
    finally:
        await cleanup_channel(username)


@pytest.mark.asyncio
async def test_feed_offset_after_filters_behaves_like_abyss(client: AsyncClient):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _, period_end = get_bucketed_period_bounds(Period.DAILY, reference=now, mode=PeriodMode.ROLLING)
    username = "abyss_filter"
    try:
        posts_data = []
        # 15 posts with views 1..15
        for i in range(1, 16):
            posts_data.append(
                {
                    "telegram_message_id": i,
                    "text": f"p{i}",
                    "permalink": f"https://t.me/abyss_filter/{i}",
                    "posted_at": period_end - timedelta(minutes=i),
                    "views": i,
                    "replies": 0,
                    "reactions_count": 0,
                }
            )
        await seed_channel_with_posts(username, posts_data)

        # Filter down to views>=4 => 12 posts: 4..15
        top = await client.get("/feed?period=daily&formula=v2&channel=abyss_filter&sort_by=views&sort_dir=desc&min_views=4&limit=10&offset=0")
        abyss = await client.get("/feed?period=daily&formula=v2&channel=abyss_filter&sort_by=views&sort_dir=desc&min_views=4&limit=10&offset=10")

        assert top.status_code == 200
        assert abyss.status_code == 200
        top_views = [p["views"] for p in top.json()["posts"]]
        abyss_views = [p["views"] for p in abyss.json()["posts"]]

        assert top_views == [15, 14, 13, 12, 11, 10, 9, 8, 7, 6]
        assert abyss_views == [5, 4]
    finally:
        await cleanup_channel(username)


@pytest.mark.asyncio
async def test_feed_v4_stored_scores_sort_by_reactions_and_filter(client: AsyncClient):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    period_start, period_end = get_bucketed_period_bounds(Period.DAILY, reference=now, mode=PeriodMode.ROLLING)
    period_hash = compute_period_hash(Period.DAILY, period_start, period_end, PeriodMode.ROLLING)
    username = "v4_stored_sort"
    try:
        posts = await seed_channel_with_posts(
            username,
            [
                {
                    "telegram_message_id": 1,
                    "text": "r1",
                    "permalink": "https://t.me/v4_stored_sort/1",
                    "posted_at": period_end - timedelta(hours=1),
                    "views": 10,
                    "replies": 1,
                    "reactions_count": 1,
                },
                {
                    "telegram_message_id": 2,
                    "text": "r10",
                    "permalink": "https://t.me/v4_stored_sort/2",
                    "posted_at": period_end - timedelta(hours=2),
                    "views": 20,
                    "replies": 2,
                    "reactions_count": 10,
                },
                {
                    "telegram_message_id": 3,
                    "text": "r5",
                    "permalink": "https://t.me/v4_stored_sort/3",
                    "posted_at": period_end - timedelta(hours=3),
                    "views": 30,
                    "replies": 3,
                    "reactions_count": 5,
                },
            ],
        )

        db = get_database()
        async with db.session() as session:
            score_repo = ScoreRepository(session)
            scores_data = []
            for idx, p in enumerate(posts, start=1):
                scores_data.append(
                    {
                        "post_id": p.id,
                        "formula_version": "v4",
                        "score": float(idx),
                        "period_start": period_start,
                        "period_end": period_end,
                        "period_hash": period_hash,
                        "global_avg_used": None,
                        "explanation": {"test": True},
                    }
                )
            await score_repo.bulk_upsert_scores(scores_data)

        resp = await client.get("/feed?period=daily&formula=v4&channel=v4_stored_sort&sort_by=reactions&sort_dir=desc&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        got = [p["reactions_count"] for p in data["posts"]]
        assert got == [10, 5, 1]
        assert data["formula"] == "v4"

        resp2 = await client.get("/feed?period=daily&formula=v4&channel=v4_stored_sort&sort_by=reactions&sort_dir=desc&min_reactions=6&limit=10")
        assert resp2.status_code == 200
        data2 = resp2.json()
        got2 = [p["reactions_count"] for p in data2["posts"]]
        assert got2 == [10]
    finally:
        await cleanup_channel(username)


@pytest.mark.asyncio
async def test_feed_filter_min_novelty(client: AsyncClient):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _, period_end = get_bucketed_period_bounds(Period.DAILY, reference=now, mode=PeriodMode.ROLLING)
    username = "novelty_filter"
    try:
        await seed_channel_with_posts(
            username,
            [
                {
                    "telegram_message_id": 1,
                    "text": "n/a",
                    "permalink": "https://t.me/novelty_filter/1",
                    "posted_at": period_end - timedelta(hours=1),
                    "views": 10,
                    "replies": 0,
                    "reactions_count": 0,
                },
                {
                    "telegram_message_id": 2,
                    "text": "low novelty",
                    "permalink": "https://t.me/novelty_filter/2",
                    "posted_at": period_end - timedelta(hours=2),
                    "views": 20,
                    "replies": 0,
                    "reactions_count": 0,
                },
                {
                    "telegram_message_id": 3,
                    "text": "high novelty",
                    "permalink": "https://t.me/novelty_filter/3",
                    "posted_at": period_end - timedelta(hours=3),
                    "views": 30,
                    "replies": 0,
                    "reactions_count": 0,
                },
            ],
        )
        await set_novelty_scores(
            {
                "https://t.me/novelty_filter/1": None,
                "https://t.me/novelty_filter/2": 0.2,
                "https://t.me/novelty_filter/3": 0.9,
            }
        )

        resp = await client.get("/feed?period=daily&formula=v2&channel=novelty_filter&min_novelty=0.5&sort_by=views&sort_dir=desc&limit=50")
        assert resp.status_code == 200
        data = resp.json()
        assert [p["permalink"] for p in data["posts"]] == ["https://t.me/novelty_filter/3"]

        resp2 = await client.get("/feed?period=daily&formula=v2&channel=novelty_filter&sort_by=novelty&sort_dir=desc&limit=50")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert [p["permalink"] for p in data2["posts"]] == [
            "https://t.me/novelty_filter/3",
            "https://t.me/novelty_filter/2",
            "https://t.me/novelty_filter/1",
        ]
    finally:
        await cleanup_channel(username)
