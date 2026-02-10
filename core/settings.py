"""Centralized settings manager with caching."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from novelty.schemas import NOVELTY_CRITERIA

# Default values for all settings
DEFAULTS: dict[str, Any] = {
    # Ranking
    "ranking.post_limit": 50000,
    "ranking.novelty_weight": 5.0,
    "ranking.avg_posts_per_day": 5.0,
    # Collector
    "collector.fetch_window_days": 1,
    "collector.deep_fetch_days": 7,
    "collector.incremental_grace_minutes": 15,
    "collector.refresh_recent_hours": 6,
    # Novelty
    "novelty.context_days": 30,
    "novelty.batch_limit": 20,
    # Automation (dynamic schedules)
    "automation.ingestion_incremental_enabled": True,
    "automation.ingestion_incremental_minutes": 5,
    "automation.ingestion_refresh_enabled": True,
    "automation.ingestion_refresh_minutes": 60,
    "automation.novelty_enabled": True,
    "automation.novelty_minutes": 5,
    "automation.rank_daily_v4_enabled": True,
    "automation.rank_daily_v4_minutes": 5,
    "automation.embeddings_enabled": True,
    "automation.embeddings_minutes": 60,
    # Novelty criteria weights (all equal by default)
    **{f"novelty.weight.{c}": 1.0 for c in NOVELTY_CRITERIA},
    # Search
    "search.enabled": True,
    "search.bm25_enabled": True,
    "search.semantic_enabled": False,
    "search.embedding_model": "baai/bge-m3",
    "search.embedding_dimensions": 1024,
    "search.embedding_batch_size": 32,
    "search.min_text_length": 30,
    "search.internal_k": 200,
    "search.fusion_k": 60,
    "search.weights.bm25": 1.0,
    "search.weights.semantic": 1.0,
}


class SettingsManager:
    """
    Centralized settings manager with in-memory caching.

    Settings are stored in database and cached in memory with TTL.
    Changes are written through to database and invalidate cache.

    Usage:
        manager = get_settings_manager()
        limit = await manager.get("ranking.post_limit")
        all_settings = await manager.get_all()
    """

    def __init__(self, cache_ttl_seconds: int = 60):
        """
        Initialize settings manager.

        Args:
            cache_ttl_seconds: How long to cache settings in memory
        """
        self._cache: dict[str, Any] = {}
        self._cache_time: datetime | None = None
        self._cache_ttl = cache_ttl_seconds
        self._lock = asyncio.Lock()

    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid."""
        if self._cache_time is None:
            return False
        elapsed = (datetime.now(timezone.utc) - self._cache_time).total_seconds()
        return elapsed < self._cache_ttl

    async def _load_from_db(self) -> dict[str, Any]:
        """Load all settings from database."""
        from storage import get_database, SettingsRepository

        db = get_database()
        async with db.session() as session:
            repo = SettingsRepository(session)
            return await repo.get_all()

    async def get_all(self, use_cache: bool = True) -> dict[str, Any]:
        """
        Get all settings merged with defaults.

        Args:
            use_cache: Whether to use cached values

        Returns:
            Dictionary of all settings with defaults filled in
        """
        async with self._lock:
            if use_cache and self._is_cache_valid():
                return {**DEFAULTS, **self._cache}

            # Load from database
            stored = await self._load_from_db()
            self._cache = stored
            self._cache_time = datetime.now(timezone.utc)

            return {**DEFAULTS, **stored}

    async def get(self, key: str, default: Any = None) -> Any:
        """
        Get a single setting value.

        Args:
            key: Setting key (e.g., "ranking.post_limit")
            default: Default value if not found (overrides DEFAULTS)

        Returns:
            Setting value
        """
        all_settings = await self.get_all()

        if key in all_settings:
            return all_settings[key]

        # Check if default provided
        if default is not None:
            return default

        # Check DEFAULTS
        return DEFAULTS.get(key)

    async def set(
        self,
        key: str,
        value: Any,
        updated_by: str | None = None,
    ) -> None:
        """
        Set a setting value (writes to database).

        Args:
            key: Setting key
            value: New value
            updated_by: Who updated the setting (for audit)
        """
        from storage import get_database, SettingsRepository

        db = get_database()
        async with db.session() as session:
            repo = SettingsRepository(session)
            await repo.set(key, value, updated_by=updated_by)
            await session.commit()

        # Invalidate cache
        await self.invalidate_cache()

    async def set_many(
        self,
        settings: dict[str, Any],
        updated_by: str | None = None,
    ) -> int:
        """
        Set multiple settings at once.

        Args:
            settings: Dictionary of key-value pairs
            updated_by: Who updated the settings

        Returns:
            Number of settings updated
        """
        from storage import get_database, SettingsRepository

        db = get_database()
        async with db.session() as session:
            repo = SettingsRepository(session)
            count = await repo.set_many(settings, updated_by=updated_by)
            await session.commit()

        # Invalidate cache
        await self.invalidate_cache()
        return count

    async def invalidate_cache(self) -> None:
        """Invalidate the settings cache."""
        async with self._lock:
            self._cache = {}
            self._cache_time = None

    # Convenience properties for common settings
    async def get_ranking_limit(self) -> int:
        """Get ranking.post_limit setting."""
        return int(await self.get("ranking.post_limit"))

    async def get_novelty_weight(self) -> float:
        """Get ranking.novelty_weight setting."""
        return float(await self.get("ranking.novelty_weight"))

    async def get_avg_posts_per_day(self) -> float:
        """Get ranking.avg_posts_per_day setting."""
        return float(await self.get("ranking.avg_posts_per_day"))

    async def get_fetch_window_days(self) -> int:
        """Get collector.fetch_window_days setting."""
        return int(await self.get("collector.fetch_window_days"))

    async def get_deep_fetch_days(self) -> int:
        """Get collector.deep_fetch_days setting."""
        return int(await self.get("collector.deep_fetch_days"))

    async def get_novelty_context_days(self) -> int:
        """Get novelty.context_days setting."""
        return int(await self.get("novelty.context_days"))

    async def get_novelty_batch_limit(self) -> int:
        """Get novelty.batch_limit setting."""
        return int(await self.get("novelty.batch_limit"))

    async def get_novelty_criteria_weights(self) -> dict[str, float]:
        """Get all novelty criteria weights as a dictionary."""
        all_settings = await self.get_all()
        return {
            criterion: float(all_settings.get(f"novelty.weight.{criterion}", 1.0))
            for criterion in NOVELTY_CRITERIA
        }


# Singleton instance
_settings_manager: SettingsManager | None = None


def get_settings_manager() -> SettingsManager:
    """Get the global settings manager instance."""
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
    return _settings_manager


def reset_settings_manager() -> None:
    """Reset the global settings manager (for testing)."""
    global _settings_manager
    _settings_manager = None


async def load_settings_for_celery() -> dict[str, Any]:
    """
    Load settings from database without singleton.

    For Celery tasks where global singleton may have async resources
    bound to a different event loop.
    """
    from storage import Database, SettingsRepository

    db = Database()
    try:
        async with db.session() as session:
            repo = SettingsRepository(session)
            stored = await repo.get_all()
            return {**DEFAULTS, **stored}
    finally:
        await db.close()
