"""Async repository classes for database operations."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from storage.models import Channel, Post, Score, Setting, Summary, TaskRun, User, Vote


class ChannelRepository:
    """Repository for Channel operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, channel_id: int) -> Channel | None:
        """Get channel by ID."""
        result = await self.session.execute(
            select(Channel).where(Channel.id == channel_id)
        )
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> Channel | None:
        """Get channel by username."""
        username = username.lstrip("@")
        result = await self.session.execute(
            select(Channel).where(Channel.username == username)
        )
        return result.scalar_one_or_none()

    async def get_all_active(self) -> Sequence[Channel]:
        """Get all active channels."""
        result = await self.session.execute(
            select(Channel).where(Channel.is_active == True).order_by(Channel.username)
        )
        return result.scalars().all()

    async def upsert(self, username: str, name: str | None = None) -> Channel:
        """Insert or update a channel."""
        username = username.lstrip("@")

        stmt = (
            pg_insert(Channel)
            .values(username=username, name=name)
            .on_conflict_do_update(
                index_elements=["username"],
                set_={"name": name, "updated_at": datetime.now(timezone.utc)},
            )
            .returning(Channel)
        )

        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()

    async def update_last_fetched(self, channel_id: int) -> None:
        """Update last_fetched_at timestamp."""
        await self.session.execute(
            update(Channel)
            .where(Channel.id == channel_id)
            .values(last_fetched_at=datetime.now(timezone.utc))
        )


class PostRepository:
    """Repository for Post operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, post_id: int) -> Post | None:
        """Get post by ID."""
        result = await self.session.execute(select(Post).where(Post.id == post_id))
        return result.scalar_one_or_none()

    async def get_by_channel_and_message_id(
        self, channel_id: int, telegram_message_id: int
    ) -> Post | None:
        """Get post by channel and Telegram message ID."""
        result = await self.session.execute(
            select(Post).where(
                Post.channel_id == channel_id,
                Post.telegram_message_id == telegram_message_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_permalink(self, permalink: str) -> Post | None:
        """Get post by permalink URL."""
        result = await self.session.execute(
            select(Post).where(Post.permalink == permalink)
        )
        return result.scalar_one_or_none()

    async def get_by_period(
        self,
        start: datetime,
        end: datetime,
        channel_id: int | None = None,
        limit: int = 100,
        load_channel: bool = True,
    ) -> Sequence[Post]:
        """
        Get posts within a time period.

        Args:
            start: Period start
            end: Period end
            channel_id: Optional channel filter
            limit: Max posts to return
            load_channel: Whether to eagerly load channel (for v2 formula stats)

        Returns:
            Sequence of Post objects
        """
        query = select(Post).where(
            Post.posted_at >= start,
            Post.posted_at <= end,
        )

        if load_channel:
            query = query.options(selectinload(Post.channel))

        if channel_id is not None:
            query = query.where(Post.channel_id == channel_id)

        query = query.order_by(Post.posted_at.desc()).limit(limit)

        result = await self.session.execute(query)
        return result.scalars().all()

    async def upsert_posts(
        self,
        channel_id: int,
        posts_data: list[dict],
    ) -> int:
        """
        Bulk upsert posts for a channel.

        Args:
            channel_id: The channel ID
            posts_data: List of dicts with keys:
                - telegram_message_id (required)
                - text (optional)
                - permalink (required)
                - posted_at (required)
                - views, forwards, replies, reactions_count (optional)
                - forwarded_from_channel_id, forwarded_from_message_id (optional)
                - media_type, edited_at (optional)

        Returns:
            Number of rows affected
        """
        if not posts_data:
            return 0

        values = []
        for post in posts_data:
            values.append(
                {
                    "channel_id": channel_id,
                    "telegram_message_id": post["telegram_message_id"],
                    "text": post.get("text"),
                    "permalink": post["permalink"],
                    "posted_at": post["posted_at"],
                    "views": post.get("views"),
                    "forwards": post.get("forwards"),
                    "replies": post.get("replies"),
                    "reactions_count": post.get("reactions_count"),
                    "forwarded_from_channel_id": post.get("forwarded_from_channel_id"),
                    "forwarded_from_message_id": post.get("forwarded_from_message_id"),
                    "media_type": post.get("media_type"),
                    "edited_at": post.get("edited_at"),
                    "grouped_id": post.get("grouped_id"),
                }
            )

        stmt = pg_insert(Post).values(values)

        stmt = stmt.on_conflict_do_update(
            constraint="uq_post_channel_message",
            set_={
                "text": stmt.excluded.text,
                "views": stmt.excluded.views,
                "forwards": stmt.excluded.forwards,
                "replies": stmt.excluded.replies,
                "reactions_count": stmt.excluded.reactions_count,
                "forwarded_from_channel_id": stmt.excluded.forwarded_from_channel_id,
                "forwarded_from_message_id": stmt.excluded.forwarded_from_message_id,
                "media_type": stmt.excluded.media_type,
                "edited_at": stmt.excluded.edited_at,
                "grouped_id": stmt.excluded.grouped_id,
                "updated_at": datetime.now(timezone.utc),
            },
        )

        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount

    async def upsert_from_collector(
        self,
        channel_username: str,
        messages: list[dict],
    ) -> int:
        """
        Upsert posts directly from collector output format.

        Args:
            channel_username: Channel username (with or without @)
            messages: List of dicts from collector with keys:
                - id: Telegram message ID
                - date: ISO datetime string
                - text: Message text
                - permalink: Post URL
                - views, forwards, replies, reactions_count (optional)
                - forwarded_from_channel_id, forwarded_from_message_id (optional)
                - media_type, edited_at (optional)

        Returns:
            Number of rows affected
        """
        channel_repo = ChannelRepository(self.session)
        channel = await channel_repo.upsert(channel_username)

        posts_data = []
        for msg in messages:
            post_data = {
                "telegram_message_id": msg["id"],
                "text": msg.get("text"),
                "permalink": msg["permalink"],
                "posted_at": datetime.fromisoformat(msg["date"]),
                "views": msg.get("views"),
                "forwards": msg.get("forwards"),
                "replies": msg.get("replies"),
                "reactions_count": msg.get("reactions_count"),
                "forwarded_from_channel_id": msg.get("forwarded_from_channel_id"),
                "forwarded_from_message_id": msg.get("forwarded_from_message_id"),
                "media_type": msg.get("media_type"),
                "grouped_id": msg.get("grouped_id"),
            }
            # Parse edited_at if present
            if msg.get("edited_at"):
                post_data["edited_at"] = datetime.fromisoformat(msg["edited_at"])
            posts_data.append(post_data)

        result = await self.upsert_posts(channel.id, posts_data)

        await channel_repo.update_last_fetched(channel.id)

        return result


class VoteRepository:
    """Repository for Vote operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_post_and_user(
        self, post_id: int, user_identifier: str
    ) -> Vote | None:
        """Get vote by post and user."""
        result = await self.session.execute(
            select(Vote).where(
                Vote.post_id == post_id,
                Vote.user_identifier == user_identifier,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_vote(
        self, post_id: int, user_identifier: str, value: int
    ) -> Vote:
        """Insert or update a vote."""
        stmt = (
            pg_insert(Vote)
            .values(post_id=post_id, user_identifier=user_identifier, value=value)
            .on_conflict_do_update(
                constraint="uq_vote_post_user",
                set_={"value": value, "updated_at": datetime.now(timezone.utc)},
            )
            .returning(Vote)
        )

        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()

    async def get_post_vote_stats(self, post_id: int) -> dict:
        """Get aggregated vote statistics for a post."""
        result = await self.session.execute(
            select(
                func.count(Vote.id).label("total"),
                func.sum(Vote.value).label("sum"),
                func.avg(Vote.value).label("avg"),
            ).where(Vote.post_id == post_id)
        )
        row = result.one()
        return {
            "total_votes": row.total or 0,
            "vote_sum": row.sum or 0,
            "vote_avg": float(row.avg) if row.avg else 0.0,
        }


class ScoreRepository:
    """Repository for Score operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_top_posts(
        self,
        formula_version: str,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        limit: int = 50,
    ) -> Sequence[Score]:
        """Get top scored posts for a period.

        If period_start/period_end are None, returns latest scores for the formula.
        """
        query = select(Score).where(Score.formula_version == formula_version)

        if period_start is not None:
            query = query.where(Score.period_start >= period_start)
        if period_end is not None:
            query = query.where(Score.period_end <= period_end)

        result = await self.session.execute(
            query.order_by(Score.score.desc()).limit(limit)
        )
        return result.scalars().all()

    async def upsert_score(
        self,
        post_id: int,
        formula_version: str,
        score: float,
        period_start: datetime,
        period_end: datetime,
        explanation: dict | None = None,
    ) -> Score:
        """Insert or update a score."""
        stmt = (
            pg_insert(Score)
            .values(
                post_id=post_id,
                formula_version=formula_version,
                score=score,
                period_start=period_start,
                period_end=period_end,
                explanation=explanation,
                computed_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                constraint="uq_score_post_formula_period",
                set_={
                    "score": score,
                    "explanation": explanation,
                    "computed_at": datetime.now(timezone.utc),
                },
            )
            .returning(Score)
        )

        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()

    async def bulk_upsert_scores(self, scores_data: list[dict]) -> int:
        """Bulk upsert scores using period_hash for uniqueness."""
        if not scores_data:
            return 0

        stmt = pg_insert(Score).values(scores_data)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_score_post_formula_hash",
            set_={
                "score": stmt.excluded.score,
                "explanation": stmt.excluded.explanation,
                "period_start": stmt.excluded.period_start,
                "period_end": stmt.excluded.period_end,
                "global_avg_used": stmt.excluded.global_avg_used,
                "computed_at": datetime.now(timezone.utc),
            },
        )

        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount


class SummaryRepository:
    """Repository for Summary operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_period(
        self,
        period_type: str,
        period_start: datetime,
        period_end: datetime,
        formula_version: str | None = None,
    ) -> Summary | None:
        """Get summary for a specific period."""
        query = select(Summary).where(
            Summary.period_type == period_type,
            Summary.period_start == period_start,
            Summary.period_end == period_end,
        )

        if formula_version:
            query = query.where(Summary.formula_version == formula_version)

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_latest(self, period_type: str, limit: int = 10) -> Sequence[Summary]:
        """Get latest summaries of a given type."""
        result = await self.session.execute(
            select(Summary)
            .where(Summary.period_type == period_type)
            .order_by(Summary.period_end.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def create(
        self,
        period_type: str,
        period_start: datetime,
        period_end: datetime,
        content_markdown: str,
        formula_version: str,
        post_count: int,
        channel_count: int,
        title: str | None = None,
        content_json: dict | None = None,
        generated_by: str | None = None,
        generation_prompt: str | None = None,
    ) -> Summary:
        """Create a new summary."""
        summary = Summary(
            period_type=period_type,
            period_start=period_start,
            period_end=period_end,
            title=title,
            content_markdown=content_markdown,
            content_json=content_json,
            formula_version=formula_version,
            post_count=post_count,
            channel_count=channel_count,
            generated_by=generated_by,
            generation_prompt=generation_prompt,
        )
        self.session.add(summary)
        await self.session.flush()
        return summary


class UserRepository:
    """Repository for User operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        """Get user by ID."""
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_provider(self, provider: str, provider_id: str) -> User | None:
        """Get user by OAuth provider and provider ID."""
        result = await self.session.execute(
            select(User).where(
                User.provider == provider,
                User.provider_id == provider_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_or_update(
        self,
        provider: str,
        provider_id: str,
        username: str | None = None,
        email: str | None = None,
        avatar_url: str | None = None,
        display_name: str | None = None,
    ) -> User:
        """Create new user or update existing one on login."""
        stmt = (
            pg_insert(User)
            .values(
                provider=provider,
                provider_id=provider_id,
                username=username,
                email=email,
                avatar_url=avatar_url,
                display_name=display_name,
                last_login_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                constraint="uq_user_provider",
                set_={
                    "username": username,
                    "email": email,
                    "avatar_url": avatar_url,
                    "display_name": display_name,
                    "last_login_at": datetime.now(timezone.utc),
                },
            )
            .returning(User)
        )

        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()


class SettingsRepository:
    """Repository for application settings."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, key: str) -> any:
        """Get setting value by key. Returns None if not found."""
        result = await self.session.execute(
            select(Setting).where(Setting.key == key)
        )
        setting = result.scalar_one_or_none()
        return setting.value if setting else None

    async def get_all(self) -> dict[str, any]:
        """Get all settings as a dictionary."""
        result = await self.session.execute(select(Setting))
        settings = result.scalars().all()
        return {s.key: s.value for s in settings}

    async def get_with_defaults(self, defaults: dict[str, any]) -> dict[str, any]:
        """Get all settings, filling missing with defaults."""
        stored = await self.get_all()
        return {**defaults, **stored}

    async def set(
        self,
        key: str,
        value: any,
        description: str | None = None,
        updated_by: str | None = None,
    ) -> Setting:
        """Set a setting value (upsert)."""
        stmt = (
            pg_insert(Setting)
            .values(
                key=key,
                value=value,
                description=description,
                updated_by=updated_by,
                updated_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "value": value,
                    "updated_at": datetime.now(timezone.utc),
                    "updated_by": updated_by,
                },
            )
            .returning(Setting)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()

    async def set_many(
        self,
        settings: dict[str, any],
        updated_by: str | None = None,
    ) -> int:
        """Set multiple settings at once."""
        count = 0
        for key, value in settings.items():
            await self.set(key, value, updated_by=updated_by)
            count += 1
        return count

    async def get_setting_object(self, key: str) -> Setting | None:
        """Get full Setting object (with metadata)."""
        result = await self.session.execute(
            select(Setting).where(Setting.key == key)
        )
        return result.scalar_one_or_none()


class TaskRunRepository:
    """Repository for task execution profiling."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        task_name: str,
        input_params: dict | None = None,
    ) -> TaskRun:
        """Create a new task run record."""
        task_run = TaskRun(
            task_name=task_name,
            input_params=input_params,
            status="running",
        )
        self.session.add(task_run)
        await self.session.flush()
        return task_run

    async def finish(
        self,
        task_run_id: int,
        status: str,
        result_summary: dict | None = None,
        error_message: str | None = None,
    ) -> TaskRun | None:
        """Mark task run as finished."""
        task_run = await self.session.get(TaskRun, task_run_id)
        if not task_run:
            return None

        now = datetime.now(timezone.utc)
        task_run.finished_at = now
        task_run.status = status
        task_run.result_summary = result_summary
        task_run.error_message = error_message

        # Calculate duration
        if task_run.started_at:
            delta = now - task_run.started_at
            task_run.duration_ms = int(delta.total_seconds() * 1000)

        await self.session.flush()
        return task_run

    async def get_recent(
        self,
        limit: int = 50,
        task_name: str | None = None,
    ) -> Sequence[TaskRun]:
        """Get recent task runs."""
        query = select(TaskRun)

        if task_name:
            query = query.where(TaskRun.task_name == task_name)

        query = query.order_by(TaskRun.started_at.desc()).limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_stats(
        self,
        task_name: str | None = None,
        days: int = 7,
    ) -> dict:
        """Get aggregated statistics for task runs."""
        from datetime import timedelta

        since = datetime.now(timezone.utc) - timedelta(days=days)

        # Base filter
        base_filter = [TaskRun.started_at >= since]
        if task_name:
            base_filter.append(TaskRun.task_name == task_name)

        # Get counts and averages per task
        stats_query = (
            select(
                TaskRun.task_name,
                func.count(TaskRun.id).label("count"),
                func.avg(TaskRun.duration_ms).label("avg_duration_ms"),
                func.max(TaskRun.duration_ms).label("max_duration_ms"),
                func.min(TaskRun.duration_ms).label("min_duration_ms"),
            )
            .where(*base_filter)
            .where(TaskRun.status == "success")
            .group_by(TaskRun.task_name)
        )
        result = await self.session.execute(stats_query)
        rows = result.fetchall()

        by_task = {}
        for row in rows:
            by_task[row.task_name] = {
                "count": row.count,
                "avg_duration_ms": round(row.avg_duration_ms, 2) if row.avg_duration_ms else 0,
                "max_duration_ms": row.max_duration_ms or 0,
                "min_duration_ms": row.min_duration_ms or 0,
            }

        # Get success rate per task
        rate_query = (
            select(
                TaskRun.task_name,
                TaskRun.status,
                func.count(TaskRun.id).label("count"),
            )
            .where(*base_filter)
            .group_by(TaskRun.task_name, TaskRun.status)
        )
        result = await self.session.execute(rate_query)
        rate_rows = result.fetchall()

        # Calculate success rates
        task_totals = {}
        task_success = {}
        for row in rate_rows:
            task_totals[row.task_name] = task_totals.get(row.task_name, 0) + row.count
            if row.status == "success":
                task_success[row.task_name] = row.count

        for name in task_totals:
            if name in by_task:
                total = task_totals[name]
                success = task_success.get(name, 0)
                by_task[name]["success_rate"] = round(success / total * 100, 1) if total > 0 else 0
                by_task[name]["total_runs"] = total

        # Overall stats
        total_query = (
            select(func.count(TaskRun.id))
            .where(*base_filter)
        )
        total_result = await self.session.execute(total_query)
        total_runs = total_result.scalar() or 0

        return {
            "by_task": by_task,
            "total_runs": total_runs,
            "days": days,
        }

    async def cleanup_old(self, days: int = 30) -> int:
        """Delete task runs older than N days."""
        from datetime import timedelta
        from sqlalchemy import delete

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            delete(TaskRun).where(TaskRun.started_at < cutoff)
        )
        await self.session.flush()
        return result.rowcount
