"""Pydantic schemas for API request/response."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Literal, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from storage.models import Post


# === Auth ===


class TelegramAuthData(BaseModel):
    """Data from Telegram Login Widget."""

    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    auth_date: int
    hash: str


class UserResponse(BaseModel):
    """User info in responses."""

    id: int
    provider: str
    username: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_admin: bool = False


class TokenResponse(BaseModel):
    """Auth token response."""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# === Feed ===


class ChannelResponse(BaseModel):
    """Channel info in post response."""

    id: int
    username: str
    name: Optional[str] = None


class PostResponse(BaseModel):
    """Post in feed response."""

    id: int
    text: Optional[str] = None
    permalink: str
    posted_at: datetime
    views: Optional[int] = None
    forwards: Optional[int] = None
    replies: Optional[int] = None
    reactions_count: Optional[int] = None
    media_type: Optional[str] = None

    # Score info
    score: float
    explanation: Optional[dict] = None

    # Novelty scoring (LLM-based information gain)
    novelty_score: Optional[float] = None

    # Channel info
    channel: ChannelResponse


def post_to_response(post: Post, score: float = 0.0, explanation: dict | None = None) -> PostResponse:
    """Convert Post ORM model to PostResponse schema."""
    return PostResponse(
        id=post.id,
        text=post.text,
        permalink=post.permalink,
        posted_at=post.posted_at,
        views=post.views,
        forwards=post.forwards,
        replies=post.replies,
        reactions_count=post.reactions_count,
        media_type=post.media_type,
        score=score,
        explanation=explanation,
        novelty_score=post.novelty_score,
        channel=ChannelResponse(
            id=post.channel.id,
            username=post.channel.username,
            name=post.channel.name,
        ),
    )


class FeedResponse(BaseModel):
    """Feed endpoint response."""

    posts: List[PostResponse]
    total: int
    period: str
    formula: str


# === Vote ===


class VoteRequest(BaseModel):
    """Vote request body."""

    post_id: int
    value: Literal[-1, 0, 1] = Field(..., description="-1=downvote, 0=remove, 1=upvote")


class VoteStats(BaseModel):
    """Vote statistics for a post."""

    total_votes: int
    vote_sum: int
    vote_avg: float


class VoteResponse(BaseModel):
    """Vote endpoint response."""

    success: bool
    post_id: int
    user_vote: int
    stats: VoteStats


# === Summary ===


class SummaryResponse(BaseModel):
    """Summary endpoint response."""

    id: int
    period_type: str
    period_start: datetime
    period_end: datetime
    title: Optional[str] = None
    content_markdown: str
    formula_version: str
    post_count: int
    channel_count: int


# === Stats ===


class StatsResponse(BaseModel):
    """System statistics response."""

    channels_count: int
    posts_count: int
    scores_count: int  # deprecated
    votes_count: int
    users_count: int
    avg_score: float = 0


# === Search ===


class SearchResultItem(BaseModel):
    """Single search result with relevance."""

    post: PostResponse
    relevance_score: float
    match_type: str  # "lexical", "semantic", "hybrid"


class SearchResponse(BaseModel):
    """Search endpoint response."""

    results: List[SearchResultItem]
    total: int
    query: str
    mode: str
    took_ms: Optional[int] = None


# === Errors ===


class ErrorResponse(BaseModel):
    """Error response."""

    detail: str
