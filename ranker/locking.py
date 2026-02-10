"""Distributed locking for ranking tasks to prevent overlaps."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RankingLock:
    """
    Distributed lock for ranking tasks using Redis.

    Prevents multiple ranking tasks from processing the same period/formula
    combination simultaneously.

    Usage:
        lock = RankingLock(redis_url="redis://localhost:6379")
        async with lock.acquire("v4", "daily", timeout=300):
            # Do ranking work
            pass
    """

    def __init__(self, redis_url: str | None = None, key_prefix: str = "ranking_lock"):
        """
        Initialize distributed lock manager.

        Args:
            redis_url: Redis connection URL (default: from REDIS_URL env)
            key_prefix: Prefix for lock keys in Redis
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.key_prefix = key_prefix
        self._redis: redis.Redis | None = None

    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    def _make_lock_key(
        self,
        formula: str,
        period: str,
        period_bucket_end: str | None = None,
    ) -> str:
        """
        Generate Redis key for lock.

        Args:
            formula: Formula version (e.g., "v1", "v4")
            period: Period type (e.g., "daily", "weekly")
            period_bucket_end: Optional period bucket end ISO timestamp

        Returns:
            Redis key string
        """
        parts = [self.key_prefix, formula, period]
        if period_bucket_end:
            parts.append(period_bucket_end)
        return ":".join(parts)

    @asynccontextmanager
    async def acquire(
        self,
        formula: str,
        period: str,
        period_bucket_end: str | None = None,
        timeout: int = 300,
        blocking_timeout: int = 10,
    ) -> AsyncGenerator[bool, None]:
        """
        Acquire distributed lock for ranking task.

        Args:
            formula: Formula version
            period: Period type
            period_bucket_end: Optional period bucket end (for precise locking)
            timeout: Lock expiry timeout in seconds (default: 300 = 5 minutes)
            blocking_timeout: Max time to wait for lock in seconds (default: 10)

        Yields:
            True if lock acquired, False otherwise

        Raises:
            redis.exceptions.LockError: If lock acquisition fails
        """
        r = await self._get_redis()
        lock_key = self._make_lock_key(formula, period, period_bucket_end)

        logger.info(
            f"Attempting to acquire lock: {lock_key} "
            f"(timeout={timeout}s, blocking={blocking_timeout}s)"
        )

        # Use Redis lock with automatic expiration
        lock = r.lock(
            lock_key,
            timeout=timeout,
            blocking_timeout=blocking_timeout,
        )

        try:
            acquired = await lock.acquire(blocking=True, blocking_timeout=blocking_timeout)

            if acquired:
                logger.info(f"Lock acquired: {lock_key}")
                yield True
            else:
                logger.warning(
                    f"Failed to acquire lock: {lock_key}. "
                    f"Another ranking task may be running."
                )
                yield False

        finally:
            # Release lock if we acquired it
            try:
                if acquired:
                    await lock.release()
                    logger.info(f"Lock released: {lock_key}")
            except Exception as e:
                logger.error(f"Error releasing lock {lock_key}: {e}")


# Global lock instance (lazy initialization)
_ranking_lock: RankingLock | None = None


def get_ranking_lock() -> RankingLock:
    """Get or create global ranking lock instance."""
    global _ranking_lock
    if _ranking_lock is None:
        _ranking_lock = RankingLock()
    return _ranking_lock


async def close_ranking_lock() -> None:
    """Close global ranking lock connection (for cleanup)."""
    global _ranking_lock
    if _ranking_lock is not None:
        await _ranking_lock.close()
        _ranking_lock = None


def reset_ranking_lock() -> None:
    """Reset global ranking lock (for testing, sync)."""
    global _ranking_lock
    _ranking_lock = None
