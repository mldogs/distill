"""Unit tests for collector module."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from collector.fetch import parse_since_date, parse_until_date_exclusive, serialize_message


class MockChannelId:
    """Mock Telethon PeerChannel."""

    def __init__(self, channel_id: int):
        self.channel_id = channel_id


class MockFwdFrom:
    """Mock Telethon MessageFwdHeader."""

    def __init__(
        self,
        from_channel_id: int | None = None,
        channel_post: int | None = None,
        
    ):
        self.from_id = MockChannelId(from_channel_id) if from_channel_id else None
        self.channel_post = channel_post


class MockReaction:
    """Mock reaction result."""

    def __init__(self, count: int):
        self.count = count


class MockReactions:
    """Mock reactions container."""

    def __init__(self, counts: list[int]):
        self.results = [MockReaction(c) for c in counts]


class MockReplies:
    """Mock replies container."""

    def __init__(self, replies: int):
        self.replies = replies


class MockMessage:
    """Mock Telethon Message object."""

    def __init__(
        self,
        id: int,
        date: datetime | None = None,
        text: str | None = "",
        views: int | None = None,
        forwards: int | None = None,
        replies: MockReplies | None = None,
        reactions: MockReactions | None = None,
        fwd_from: MockFwdFrom | None = None,
        media: object | None = None,
        edit_date: datetime | None = None,
        grouped_id: int | None = None,
    ):
        self.id = id
        self.date = date or datetime.now(timezone.utc)
        self.text = text
        self.views = views
        self.forwards = forwards
        self.replies = replies
        self.reactions = reactions
        self.fwd_from = fwd_from
        self.media = media
        self.edit_date = edit_date
        self.grouped_id = grouped_id


class TestSerializeMessageBasic:
    """Tests for basic message serialization."""

    def test_basic_fields(self):
        """Test basic message fields are serialized."""
        msg = MockMessage(
            id=123,
            date=datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc),
            text="Hello world",
        )

        result = serialize_message(msg, "test_channel")

        assert result["id"] == 123
        assert result["date"] == "2026-01-10T12:00:00+00:00"
        assert result["text"] == "Hello world"
        assert result["permalink"] == "https://t.me/test_channel/123"

    def test_empty_text(self):
        """Test message with empty text."""
        msg = MockMessage(id=1, text=None)

        result = serialize_message(msg, "channel")

        assert result["text"] is None

    def test_engagement_metrics(self):
        """Test views, forwards, reactions are captured."""
        msg = MockMessage(
            id=1,
            views=1000,
            forwards=50,
            replies=MockReplies(10),
            reactions=MockReactions([30, 20, 10]),
        )

        result = serialize_message(msg, "channel")

        assert result["views"] == 1000
        assert result["forwards"] == 50
        assert result["replies"] == 10
        assert result["reactions_count"] == 60  # 30 + 20 + 10

    def test_no_engagement_metrics(self):
        """Test message without engagement metrics."""
        msg = MockMessage(id=1)

        result = serialize_message(msg, "channel")

        assert "views" not in result
        assert "forwards" not in result
        assert "replies" not in result
        assert "reactions_count" not in result


class TestSerializeMessageForwardInfo:
    """Tests for forward info serialization."""

    def test_forwarded_message_full_info(self):
        """Test forwarded message with channel ID and message ID."""
        msg = MockMessage(
            id=1,
            fwd_from=MockFwdFrom(
                from_channel_id=9876543210,
                channel_post=456,
            ),
        )

        result = serialize_message(msg, "channel")

        assert result["forwarded_from_channel_id"] == 9876543210
        assert result["forwarded_from_message_id"] == 456

    def test_forwarded_message_channel_only(self):
        """Test forwarded message with only channel ID."""
        msg = MockMessage(
            id=1,
            fwd_from=MockFwdFrom(
                from_channel_id=1234567890,
                channel_post=None,
            ),
        )

        result = serialize_message(msg, "channel")

        assert result["forwarded_from_channel_id"] == 1234567890
        assert "forwarded_from_message_id" not in result

    def test_forwarded_message_no_channel(self):
        """Test forwarded from non-channel source (user forward)."""
        fwd = MagicMock()
        fwd.from_id = None  # User forward, no channel
        fwd.channel_post = None

        msg = MockMessage(id=1, fwd_from=fwd)

        result = serialize_message(msg, "channel")

        assert "forwarded_from_channel_id" not in result
        assert "forwarded_from_message_id" not in result

    def test_not_forwarded(self):
        """Test original (not forwarded) message."""
        msg = MockMessage(id=1, fwd_from=None)

        result = serialize_message(msg, "channel")

        assert "forwarded_from_channel_id" not in result
        assert "forwarded_from_message_id" not in result


class TestSerializeMessageMediaType:
    """Tests for media type serialization."""

    def test_photo_media(self):
        """Test message with photo."""

        class MessageMediaPhoto:
            pass

        msg = MockMessage(id=1, media=MessageMediaPhoto())

        result = serialize_message(msg, "channel")

        assert result["media_type"] == "MessageMediaPhoto"

    def test_video_media(self):
        """Test message with video."""

        class MessageMediaDocument:
            pass

        msg = MockMessage(id=1, media=MessageMediaDocument())

        result = serialize_message(msg, "channel")

        assert result["media_type"] == "MessageMediaDocument"

    def test_webpage_media(self):
        """Test message with web page preview."""

        class MessageMediaWebPage:
            pass

        msg = MockMessage(id=1, media=MessageMediaWebPage())

        result = serialize_message(msg, "channel")

        assert result["media_type"] == "MessageMediaWebPage"

    def test_no_media(self):
        """Test message without media."""
        msg = MockMessage(id=1, media=None)

        result = serialize_message(msg, "channel")

        assert "media_type" not in result


class TestSerializeMessageEditDate:
    """Tests for edit date serialization."""

    def test_edited_message(self):
        """Test message that was edited."""
        edit_time = datetime(2026, 1, 10, 14, 30, 0, tzinfo=timezone.utc)
        msg = MockMessage(id=1, edit_date=edit_time)

        result = serialize_message(msg, "channel")

        assert result["edited_at"] == "2026-01-10T14:30:00+00:00"

    def test_not_edited(self):
        """Test message that was never edited."""
        msg = MockMessage(id=1, edit_date=None)

        result = serialize_message(msg, "channel")

        assert "edited_at" not in result


class TestSerializeMessageComplete:
    """Integration tests for complete message serialization."""

    def test_full_message_with_all_fields(self):
        """Test message with all possible fields populated."""

        class MessageMediaPhoto:
            pass

        msg = MockMessage(
            id=999,
            date=datetime(2026, 1, 10, 10, 0, 0, tzinfo=timezone.utc),
            text="Check out this post from another channel!",
            views=5000,
            forwards=100,
            replies=MockReplies(25),
            reactions=MockReactions([50, 30, 20]),
            fwd_from=MockFwdFrom(
                from_channel_id=1111111111,
                channel_post=777,
            ),
            media=MessageMediaPhoto(),
            edit_date=datetime(2026, 1, 10, 11, 0, 0, tzinfo=timezone.utc),
        )

        result = serialize_message(msg, "my_channel")

        # Basic fields
        assert result["id"] == 999
        assert result["date"] == "2026-01-10T10:00:00+00:00"
        assert result["text"] == "Check out this post from another channel!"
        assert result["permalink"] == "https://t.me/my_channel/999"

        # Engagement
        assert result["views"] == 5000
        assert result["forwards"] == 100
        assert result["replies"] == 25
        assert result["reactions_count"] == 100  # 50 + 30 + 20

        # Forward info
        assert result["forwarded_from_channel_id"] == 1111111111
        assert result["forwarded_from_message_id"] == 777

        # Media
        assert result["media_type"] == "MessageMediaPhoto"

        # Edit
        assert result["edited_at"] == "2026-01-10T11:00:00+00:00"

    def test_minimal_message(self):
        """Test message with minimal fields (text only)."""
        msg = MockMessage(
            id=1,
            date=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            text="Simple text message",
        )

        result = serialize_message(msg, "channel")

        assert result == {
            "id": 1,
            "date": "2026-01-01T00:00:00+00:00",
            "text": "Simple text message",
            "permalink": "https://t.me/channel/1",
        }


class TestDateParsing:
    """Tests for date parsing helpers."""

    def test_parse_since_date_midnight_utc(self):
        dt = parse_since_date("2026-01-10")
        assert dt == datetime(2026, 1, 10, 0, 0, 0, tzinfo=timezone.utc)

    def test_parse_until_date_is_exclusive_next_day(self):
        dt = parse_until_date_exclusive("2026-01-10")
        assert dt == datetime(2026, 1, 11, 0, 0, 0, tzinfo=timezone.utc)
