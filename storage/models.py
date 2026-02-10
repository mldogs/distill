"""SQLAlchemy async models for Telegram Post Exchange."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class PeriodType(str, Enum):
    """Summary period types."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class Channel(Base):
    """Telegram channel metadata."""

    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    last_fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Channel statistics for relative scoring (v2/v4)
    avg_views_30d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_forwards_30d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    median_engagement_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    posts_count_30d: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    posts_per_day_30d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # v4: frequency penalty
    stats_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    posts: Mapped[list["Post"]] = relationship(
        "Post", back_populates="channel", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<Channel(id={self.id}, username='{self.username}')>"


class Post(Base):
    """Telegram post/message."""

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    permalink: Mapped[str] = mapped_column(String(512), nullable=False)

    views: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    forwards: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    replies: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reactions_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Forward info — для графа связей
    forwarded_from_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    forwarded_from_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Media & edit tracking
    media_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Album grouping (Telegram groups multiple photos/videos into one visual post)
    grouped_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Novelty scoring (LLM-based information gain)
    novelty_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    novelty_explanation: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Full-text search (generated column)
    search_vector = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('russian', coalesce(text, ''))", persisted=True),
        nullable=True,
    )

    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    channel: Mapped["Channel"] = relationship("Channel", back_populates="posts")
    votes: Mapped[list["Vote"]] = relationship(
        "Vote", back_populates="post", lazy="select"
    )
    scores: Mapped[list["Score"]] = relationship(
        "Score", back_populates="post", lazy="select"
    )

    __table_args__ = (
        UniqueConstraint(
            "channel_id", "telegram_message_id", name="uq_post_channel_message"
        ),
        Index("ix_posts_posted_at", "posted_at"),
        Index("ix_posts_channel_posted", "channel_id", "posted_at"),
        Index("ix_posts_permalink", "permalink"),
        Index("ix_posts_forwarded_from", "forwarded_from_channel_id"),
        Index("ix_posts_novelty_score", "novelty_score"),
        Index("ix_posts_grouped_id", "channel_id", "grouped_id"),
        Index("ix_posts_search_vector", "search_vector", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        return f"<Post(id={self.id}, channel_id={self.channel_id}, tg_id={self.telegram_message_id})>"


class PostEmbedding(Base):
    """Vector embedding for a post (semantic search)."""

    __tablename__ = "post_embeddings"

    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False, default="baai/bge-m3")
    embedding = mapped_column(Vector(1024), nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    post: Mapped["Post"] = relationship("Post")

    __table_args__ = (
        Index("ix_post_embeddings_model", "model"),
        Index("ix_post_embeddings_text_hash", "text_hash"),
    )

    def __repr__(self) -> str:
        return f"<PostEmbedding(post_id={self.post_id}, model='{self.model}')>"


class Vote(Base):
    """User vote on a post."""

    __tablename__ = "votes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )

    user_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    post: Mapped["Post"] = relationship("Post", back_populates="votes")

    __table_args__ = (
        UniqueConstraint("post_id", "user_identifier", name="uq_vote_post_user"),
        Index("ix_votes_post_id", "post_id"),
    )

    def __repr__(self) -> str:
        return f"<Vote(id={self.id}, post_id={self.post_id}, value={self.value})>"


class Score(Base):
    """Computed score for a post with explanation."""

    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )

    formula_version: Mapped[str] = mapped_column(String(50), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)

    explanation: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Period identification for exact matching and deduplication
    period_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Reproducibility: store global_avg used for v4 formula
    global_avg_used: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    post: Mapped["Post"] = relationship("Post", back_populates="scores")

    __table_args__ = (
        # Primary uniqueness constraint using period_hash
        UniqueConstraint(
            "post_id",
            "formula_version",
            "period_hash",
            name="uq_score_post_formula_hash",
        ),
        # Fast lookup by formula and period_hash
        Index("ix_scores_formula_hash_score", "formula_version", "period_hash", "score"),
        Index("ix_scores_formula_score", "formula_version", "score"),
        Index("ix_scores_period", "period_start", "period_end"),
        Index("ix_scores_period_hash", "period_hash"),
    )

    def __repr__(self) -> str:
        return f"<Score(id={self.id}, post_id={self.post_id}, formula={self.formula_version}, score={self.score})>"


class Summary(Base):
    """Generated summary (daily/weekly/monthly)."""

    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    period_type: Mapped[str] = mapped_column(String(20), nullable=False)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    content_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    formula_version: Mapped[str] = mapped_column(String(50), nullable=False)
    post_count: Mapped[int] = mapped_column(Integer, nullable=False)
    channel_count: Mapped[int] = mapped_column(Integer, nullable=False)

    generated_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    generation_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "period_type",
            "period_start",
            "period_end",
            "formula_version",
            name="uq_summary_period_formula",
        ),
        Index("ix_summaries_period_type", "period_type"),
        Index("ix_summaries_period", "period_start", "period_end"),
    )

    def __repr__(self) -> str:
        return f"<Summary(id={self.id}, type={self.period_type}, start={self.period_start})>"


class User(Base):
    """User account for authentication."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # OAuth provider info
    provider: Mapped[str] = mapped_column(String(20), nullable=False)  # telegram, google
    provider_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # User profile
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("provider", "provider_id", name="uq_user_provider"),
        Index("ix_users_provider_id", "provider", "provider_id"),
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, provider='{self.provider}', username='{self.username}')>"


class Setting(Base):
    """Dynamic application settings (key-value store)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    def __repr__(self) -> str:
        return f"<Setting(key='{self.key}')>"


class TaskRun(Base):
    """Task execution profiling data."""

    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    task_name: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), default="running", nullable=False
    )  # running, success, failed, timeout

    input_params: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    result_summary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_task_runs_task_started", "task_name", "started_at"),
        Index("ix_task_runs_status", "status"),
        Index("ix_task_runs_started_at", "started_at"),
    )

    def __repr__(self) -> str:
        return f"<TaskRun(id={self.id}, task='{self.task_name}', status='{self.status}')>"
