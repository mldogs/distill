"""Feature extraction from posts for scoring."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage.models import Post


@dataclass(frozen=True)
class PostFeatures:
    """Extracted features from a post for scoring."""

    post_id: int
    views: int
    forwards: int
    replies: int
    reactions: int
    age_hours: float
    novelty_score: float | None = None

    # Channel context for v2/v4 formula (relative scoring + frequency penalty)
    channel_avg_views: float | None = None
    channel_avg_forwards: float | None = None
    channel_median_engagement: float | None = None
    channel_posts_per_day: float | None = None  # v4: frequency penalty
    global_avg_posts_per_day: float | None = None  # v4: baseline for frequency penalty

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "post_id": self.post_id,
            "views": self.views,
            "forwards": self.forwards,
            "replies": self.replies,
            "reactions": self.reactions,
            "age_hours": self.age_hours,
            "novelty_score": self.novelty_score,
            "channel_avg_views": self.channel_avg_views,
            "channel_avg_forwards": self.channel_avg_forwards,
            "channel_median_engagement": self.channel_median_engagement,
            "channel_posts_per_day": self.channel_posts_per_day,
            "global_avg_posts_per_day": self.global_avg_posts_per_day,
        }


def extract_features(
    post: "Post",
    reference_time: datetime | None = None,
    channel_stats: dict | None = None,
    global_avg_posts_per_day: float | None = None,
) -> PostFeatures:
    """
    Extract scoring features from a Post object.

    Args:
        post: Post model instance
        reference_time: Reference time for age calculation (default: now UTC)
        channel_stats: Optional dict with channel statistics for v2 formula:
            - avg_views_30d: float
            - avg_forwards_30d: float
            - median_engagement_rate: float
            - posts_per_day_30d: float
        global_avg_posts_per_day: Global average posts per day across all channels (v4)

    Returns:
        PostFeatures dataclass with normalized values
    """
    if reference_time is None:
        reference_time = datetime.now(timezone.utc)

    # Ensure reference_time has timezone
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    # Calculate age in hours
    posted_at = post.posted_at
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)

    age_delta = reference_time - posted_at
    age_hours = max(0.0, age_delta.total_seconds() / 3600)

    # Extract channel context if available
    channel_avg_views = None
    channel_avg_forwards = None
    channel_median_engagement = None
    channel_posts_per_day = None

    if channel_stats:
        channel_avg_views = channel_stats.get("avg_views_30d")
        channel_avg_forwards = channel_stats.get("avg_forwards_30d")
        channel_median_engagement = channel_stats.get("median_engagement_rate")
        channel_posts_per_day = channel_stats.get("posts_per_day_30d")
    elif hasattr(post, "channel") and post.channel:
        # Try to get from loaded channel relationship
        channel_avg_views = getattr(post.channel, "avg_views_30d", None)
        channel_avg_forwards = getattr(post.channel, "avg_forwards_30d", None)
        channel_median_engagement = getattr(post.channel, "median_engagement_rate", None)
        channel_posts_per_day = getattr(post.channel, "posts_per_day_30d", None)

    return PostFeatures(
        post_id=post.id,
        views=post.views or 0,
        forwards=post.forwards or 0,
        replies=post.replies or 0,
        reactions=post.reactions_count or 0,
        age_hours=age_hours,
        novelty_score=post.novelty_score,
        channel_avg_views=channel_avg_views,
        channel_avg_forwards=channel_avg_forwards,
        channel_median_engagement=channel_median_engagement,
        channel_posts_per_day=channel_posts_per_day,
        global_avg_posts_per_day=global_avg_posts_per_day,
    )


def extract_features_from_dict(
    data: dict,
    reference_time: datetime | None = None,
    channel_stats: dict | None = None,
    global_avg_posts_per_day: float | None = None,
) -> PostFeatures:
    """
    Extract scoring features from a dictionary.

    Useful for testing or when Post object is not available.

    Args:
        data: Dictionary with post data
        reference_time: Reference time for age calculation
        channel_stats: Optional dict with channel statistics for v2 formula

    Returns:
        PostFeatures dataclass
    """
    if reference_time is None:
        reference_time = datetime.now(timezone.utc)

    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    posted_at = data.get("posted_at")
    if posted_at is None:
        age_hours = 0.0
    else:
        if isinstance(posted_at, str):
            posted_at = datetime.fromisoformat(posted_at)
        if posted_at.tzinfo is None:
            posted_at = posted_at.replace(tzinfo=timezone.utc)
        age_delta = reference_time - posted_at
        age_hours = max(0.0, age_delta.total_seconds() / 3600)

    # Extract channel context
    channel_avg_views = None
    channel_avg_forwards = None
    channel_median_engagement = None
    channel_posts_per_day = None

    if channel_stats:
        channel_avg_views = channel_stats.get("avg_views_30d")
        channel_avg_forwards = channel_stats.get("avg_forwards_30d")
        channel_median_engagement = channel_stats.get("median_engagement_rate")
        channel_posts_per_day = channel_stats.get("posts_per_day_30d")
    else:
        # Try to get from data dict itself
        channel_avg_views = data.get("channel_avg_views")
        channel_avg_forwards = data.get("channel_avg_forwards")
        channel_median_engagement = data.get("channel_median_engagement")
        channel_posts_per_day = data.get("channel_posts_per_day")

    return PostFeatures(
        post_id=data.get("id", 0),
        views=data.get("views") or 0,
        forwards=data.get("forwards") or 0,
        replies=data.get("replies") or 0,
        reactions=data.get("reactions_count") or data.get("reactions") or 0,
        age_hours=age_hours,
        novelty_score=data.get("novelty_score"),
        channel_avg_views=channel_avg_views,
        channel_avg_forwards=channel_avg_forwards,
        channel_median_engagement=channel_median_engagement,
        channel_posts_per_day=channel_posts_per_day,
        global_avg_posts_per_day=global_avg_posts_per_day or data.get("global_avg_posts_per_day"),
    )
