"""Integration tests for storage module."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text

from storage import Database, ChannelRepository, PostRepository


def unique_name(prefix: str) -> str:
    """Generate unique name for test isolation."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest_asyncio.fixture
async def db():
    """Create database connection for tests."""
    database = Database()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def session(db):
    """Create database session with rollback for test isolation."""
    async with db.engine.connect() as conn:
        # Start a transaction that we'll roll back
        trans = await conn.begin()

        # Create a session bound to this connection
        from sqlalchemy.ext.asyncio import AsyncSession
        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
            yield session

        # Rollback the transaction - all test data is discarded
        await trans.rollback()


class TestPostRepositoryNewFields:
    """Tests for PostRepository with new fields (forward, media, edit)."""

    @pytest.mark.asyncio
    async def test_upsert_post_with_forward_info(self, session):
        """Test upserting a post with forward information."""
        channel_repo = ChannelRepository(session)
        post_repo = PostRepository(session)

        # Create channel
        channel = await channel_repo.upsert("test_forward_channel")
        await session.flush()

        # Create post with forward info
        posts_data = [
            {
                "telegram_message_id": 10001,
                "text": "Forwarded post",
                "permalink": "https://t.me/test_forward_channel/10001",
                "posted_at": datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc),
                "views": 1000,
                "forwarded_from_channel_id": 9876543210,
                "forwarded_from_message_id": 555,
            }
        ]

        count = await post_repo.upsert_posts(channel.id, posts_data)
        assert count == 1

        # Retrieve and verify
        post = await post_repo.get_by_channel_and_message_id(channel.id, 10001)
        assert post is not None
        assert post.forwarded_from_channel_id == 9876543210
        assert post.forwarded_from_message_id == 555

    @pytest.mark.asyncio
    async def test_upsert_post_with_media_type(self, session):
        """Test upserting a post with media type."""
        channel_repo = ChannelRepository(session)
        post_repo = PostRepository(session)

        channel = await channel_repo.upsert("test_media_channel")
        await session.flush()

        posts_data = [
            {
                "telegram_message_id": 10002,
                "text": "Photo post",
                "permalink": "https://t.me/test_media_channel/10002",
                "posted_at": datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc),
                "media_type": "MessageMediaPhoto",
            }
        ]

        await post_repo.upsert_posts(channel.id, posts_data)

        post = await post_repo.get_by_channel_and_message_id(channel.id, 10002)
        assert post is not None
        assert post.media_type == "MessageMediaPhoto"

    @pytest.mark.asyncio
    async def test_upsert_post_with_edited_at(self, session):
        """Test upserting a post with edit timestamp."""
        channel_repo = ChannelRepository(session)
        post_repo = PostRepository(session)

        channel = await channel_repo.upsert("test_edit_channel")
        await session.flush()

        edit_time = datetime(2026, 1, 10, 14, 30, 0, tzinfo=timezone.utc)
        posts_data = [
            {
                "telegram_message_id": 10003,
                "text": "Edited post",
                "permalink": "https://t.me/test_edit_channel/10003",
                "posted_at": datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc),
                "edited_at": edit_time,
            }
        ]

        await post_repo.upsert_posts(channel.id, posts_data)

        post = await post_repo.get_by_channel_and_message_id(channel.id, 10003)
        assert post is not None
        assert post.edited_at == edit_time

    @pytest.mark.asyncio
    async def test_upsert_post_with_all_new_fields(self, session):
        """Test upserting a post with all new fields."""
        channel_repo = ChannelRepository(session)
        post_repo = PostRepository(session)

        channel = await channel_repo.upsert("test_all_fields_channel")
        await session.flush()

        edit_time = datetime(2026, 1, 10, 15, 0, 0, tzinfo=timezone.utc)
        posts_data = [
            {
                "telegram_message_id": 10004,
                "text": "Complete post with all fields",
                "permalink": "https://t.me/test_all_fields_channel/10004",
                "posted_at": datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc),
                "views": 5000,
                "forwards": 100,
                "replies": 25,
                "reactions_count": 500,
                "forwarded_from_channel_id": 1111111111,
                "forwarded_from_message_id": 999,
                "media_type": "MessageMediaDocument",
                "edited_at": edit_time,
            }
        ]

        await post_repo.upsert_posts(channel.id, posts_data)

        post = await post_repo.get_by_channel_and_message_id(channel.id, 10004)
        assert post is not None
        assert post.views == 5000
        assert post.forwards == 100
        assert post.replies == 25
        assert post.reactions_count == 500
        assert post.forwarded_from_channel_id == 1111111111
        assert post.forwarded_from_message_id == 999
        assert post.media_type == "MessageMediaDocument"
        assert post.edited_at == edit_time

    @pytest.mark.asyncio
    async def test_upsert_updates_new_fields(self, session):
        """Test that upsert updates new fields on conflict."""
        channel_repo = ChannelRepository(session)
        post_repo = PostRepository(session)

        channel = await channel_repo.upsert("test_update_channel")
        await session.flush()

        # First insert without forward info
        posts_data = [
            {
                "telegram_message_id": 10005,
                "text": "Original post",
                "permalink": "https://t.me/test_update_channel/10005",
                "posted_at": datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc),
            }
        ]
        await post_repo.upsert_posts(channel.id, posts_data)
        await session.flush()

        # Update with new fields
        posts_data[0]["forwarded_from_channel_id"] = 2222222222
        posts_data[0]["media_type"] = "MessageMediaPhoto"
        posts_data[0]["edited_at"] = datetime(2026, 1, 10, 16, 0, 0, tzinfo=timezone.utc)

        await post_repo.upsert_posts(channel.id, posts_data)

        post = await post_repo.get_by_channel_and_message_id(channel.id, 10005)
        assert post is not None
        assert post.forwarded_from_channel_id == 2222222222
        assert post.media_type == "MessageMediaPhoto"
        assert post.edited_at is not None


class TestPostRepositoryCollectorFormat:
    """Tests for upsert_from_collector with new fields."""

    @pytest.mark.asyncio
    async def test_collector_format_with_forward_info(self, session):
        """Test importing collector data with forward information."""
        post_repo = PostRepository(session)

        messages = [
            {
                "id": 20001,
                "date": "2026-01-10T12:00:00+00:00",
                "text": "Forwarded from another channel",
                "permalink": "https://t.me/collector_test/20001",
                "views": 2000,
                "forwarded_from_channel_id": 3333333333,
                "forwarded_from_message_id": 111,
            }
        ]

        count = await post_repo.upsert_from_collector("collector_test", messages)
        assert count == 1

        post = await post_repo.get_by_permalink("https://t.me/collector_test/20001")
        assert post is not None
        assert post.forwarded_from_channel_id == 3333333333
        assert post.forwarded_from_message_id == 111

    @pytest.mark.asyncio
    async def test_collector_format_with_media_type(self, session):
        """Test importing collector data with media type."""
        post_repo = PostRepository(session)

        messages = [
            {
                "id": 20002,
                "date": "2026-01-10T12:00:00+00:00",
                "text": "Photo message",
                "permalink": "https://t.me/collector_test2/20002",
                "media_type": "MessageMediaPhoto",
            }
        ]

        await post_repo.upsert_from_collector("collector_test2", messages)

        post = await post_repo.get_by_permalink("https://t.me/collector_test2/20002")
        assert post is not None
        assert post.media_type == "MessageMediaPhoto"

    @pytest.mark.asyncio
    async def test_collector_format_with_edited_at(self, session):
        """Test importing collector data with edit timestamp."""
        post_repo = PostRepository(session)

        messages = [
            {
                "id": 20003,
                "date": "2026-01-10T12:00:00+00:00",
                "text": "Edited message",
                "permalink": "https://t.me/collector_test3/20003",
                "edited_at": "2026-01-10T14:30:00+00:00",
            }
        ]

        await post_repo.upsert_from_collector("collector_test3", messages)

        post = await post_repo.get_by_permalink("https://t.me/collector_test3/20003")
        assert post is not None
        assert post.edited_at is not None
        assert post.edited_at.hour == 14
        assert post.edited_at.minute == 30

    @pytest.mark.asyncio
    async def test_collector_format_complete(self, session):
        """Test importing complete collector data with all fields."""
        post_repo = PostRepository(session)

        messages = [
            {
                "id": 20004,
                "date": "2026-01-10T10:00:00+00:00",
                "text": "Complete message from collector",
                "permalink": "https://t.me/collector_full/20004",
                "views": 10000,
                "forwards": 200,
                "replies": 50,
                "reactions_count": 1000,
                "forwarded_from_channel_id": 4444444444,
                "forwarded_from_message_id": 222,
                "media_type": "MessageMediaWebPage",
                "edited_at": "2026-01-10T11:00:00+00:00",
            }
        ]

        await post_repo.upsert_from_collector("collector_full", messages)

        post = await post_repo.get_by_permalink("https://t.me/collector_full/20004")
        assert post is not None

        # Verify all fields
        assert post.views == 10000
        assert post.forwards == 200
        assert post.replies == 50
        assert post.reactions_count == 1000
        assert post.forwarded_from_channel_id == 4444444444
        assert post.forwarded_from_message_id == 222
        assert post.media_type == "MessageMediaWebPage"
        assert post.edited_at is not None


class TestPostRepositoryNullFields:
    """Tests for handling NULL values in new fields."""

    @pytest.mark.asyncio
    async def test_null_forward_fields(self, session):
        """Test that NULL forward fields are handled correctly."""
        channel_repo = ChannelRepository(session)
        post_repo = PostRepository(session)

        channel = await channel_repo.upsert("test_null_channel")
        await session.flush()

        posts_data = [
            {
                "telegram_message_id": 30001,
                "text": "Regular post without forward",
                "permalink": "https://t.me/test_null_channel/30001",
                "posted_at": datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc),
                "forwarded_from_channel_id": None,
                "forwarded_from_message_id": None,
                "media_type": None,
                "edited_at": None,
            }
        ]

        await post_repo.upsert_posts(channel.id, posts_data)

        post = await post_repo.get_by_channel_and_message_id(channel.id, 30001)
        assert post is not None
        assert post.forwarded_from_channel_id is None
        assert post.forwarded_from_message_id is None
        assert post.media_type is None
        assert post.edited_at is None

    @pytest.mark.asyncio
    async def test_missing_new_fields_default_to_none(self, session):
        """Test that missing new fields default to None."""
        channel_repo = ChannelRepository(session)
        post_repo = PostRepository(session)

        channel = await channel_repo.upsert("test_missing_channel")
        await session.flush()

        # Post data without new fields
        posts_data = [
            {
                "telegram_message_id": 30002,
                "text": "Post without new fields",
                "permalink": "https://t.me/test_missing_channel/30002",
                "posted_at": datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc),
            }
        ]

        await post_repo.upsert_posts(channel.id, posts_data)

        post = await post_repo.get_by_channel_and_message_id(channel.id, 30002)
        assert post is not None
        assert post.forwarded_from_channel_id is None
        assert post.forwarded_from_message_id is None
        assert post.media_type is None
        assert post.edited_at is None


class TestPostRepositoryTextNullability:
    """Tests for updating Post.text between string and NULL."""

    @pytest.mark.asyncio
    async def test_upsert_can_set_text_to_null(self, session):
        """Collector can emit text=None; upsert should persist NULL."""
        channel_repo = ChannelRepository(session)
        post_repo = PostRepository(session)

        channel = await channel_repo.upsert("test_text_null_channel")
        await session.flush()

        posts_data = [
            {
                "telegram_message_id": 20001,
                "text": "Initial text",
                "permalink": "https://t.me/test_text_null_channel/20001",
                "posted_at": datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc),
            }
        ]
        await post_repo.upsert_posts(channel.id, posts_data)
        await session.flush()

        post = await post_repo.get_by_channel_and_message_id(channel.id, 20001)
        assert post is not None
        assert post.text == "Initial text"

        posts_data[0]["text"] = None
        await post_repo.upsert_posts(channel.id, posts_data)
        await session.flush()

        session.expire(post)
        await session.refresh(post)
        assert post.text is None

    @pytest.mark.asyncio
    async def test_upsert_can_set_text_from_null_to_string(self, session):
        """If a post later gets a caption/text, upsert should update it."""
        channel_repo = ChannelRepository(session)
        post_repo = PostRepository(session)

        channel = await channel_repo.upsert("test_text_from_null_channel")
        await session.flush()

        posts_data = [
            {
                "telegram_message_id": 20002,
                "text": None,
                "permalink": "https://t.me/test_text_from_null_channel/20002",
                "posted_at": datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc),
            }
        ]
        await post_repo.upsert_posts(channel.id, posts_data)
        await session.flush()

        post = await post_repo.get_by_channel_and_message_id(channel.id, 20002)
        assert post is not None
        assert post.text is None

        posts_data[0]["text"] = "Now has text"
        await post_repo.upsert_posts(channel.id, posts_data)
        await session.flush()

        session.expire(post)
        await session.refresh(post)
        assert post.text == "Now has text"


class TestChannelRepository:
    """Tests for ChannelRepository."""

    @pytest.mark.asyncio
    async def test_upsert_channel(self, session):
        """Test channel upsert creates and updates."""
        channel_repo = ChannelRepository(session)
        channel_name = unique_name("upsert_test")

        # Create
        channel = await channel_repo.upsert(channel_name, "Test Name")
        await session.flush()
        assert channel.username == channel_name
        assert channel.name == "Test Name"
        original_id = channel.id

        # Expire cached object to force fresh fetch
        session.expire_all()

        # Update (same username)
        await channel_repo.upsert(channel_name, "Updated Name")
        await session.flush()

        # Expire again before fetch
        session.expire_all()

        # Fetch to verify update
        updated = await channel_repo.get_by_username(channel_name)
        assert updated is not None
        assert updated.id == original_id
        assert updated.name == "Updated Name"

    @pytest.mark.asyncio
    async def test_get_by_username_strips_at(self, session):
        """Test that get_by_username strips @ prefix."""
        channel_repo = ChannelRepository(session)

        await channel_repo.upsert("strip_test", "Test")
        await session.flush()

        # Both should work
        channel1 = await channel_repo.get_by_username("strip_test")
        channel2 = await channel_repo.get_by_username("@strip_test")

        assert channel1 is not None
        assert channel2 is not None
        assert channel1.id == channel2.id
