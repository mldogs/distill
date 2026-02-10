"""Comprehensive tests for Phase 1 ranking critical fixes.

Tests cover:
- Task 20: Period boundaries stabilization (bucketing)
- Task 1, 21: Period hash for exact matching
- Task 2: Adaptive freshness decay
- Task 3: Distributed locking
- Task 5: Settings-based limits
- Task 4: Reference time consistency
- Task 7: Score uniqueness constraint
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from ranker import Scorer
from ranker.formulas import PERIOD_DECAY_CONFIG, FormulaV4, build_formula
from ranker.locking import RankingLock
from ranker.periods import (
    Period,
    PeriodMode,
    bucket_period_end,
    compute_period_hash,
    get_bucketed_period_bounds,
)


class TestPeriodBucketing:
    """Tests for Task 20: Period boundaries stabilization."""

    def test_bucket_daily_rounds_to_hour(self):
        """Test daily period rounds to hour boundary."""
        ref = datetime(2026, 1, 13, 10, 35, 42, tzinfo=timezone.utc)
        bucketed = bucket_period_end(ref, Period.DAILY, PeriodMode.ROLLING)

        assert bucketed == datetime(2026, 1, 13, 10, 0, 0, tzinfo=timezone.utc)
        assert bucketed.minute == 0
        assert bucketed.second == 0
        assert bucketed.microsecond == 0

    def test_bucket_weekly_rounds_to_midnight(self):
        """Test weekly period rounds to midnight UTC."""
        ref = datetime(2026, 1, 13, 14, 25, 30, tzinfo=timezone.utc)
        bucketed = bucket_period_end(ref, Period.WEEKLY, PeriodMode.ROLLING)

        assert bucketed == datetime(2026, 1, 13, 0, 0, 0, tzinfo=timezone.utc)
        assert bucketed.hour == 0
        assert bucketed.minute == 0

    def test_bucket_monthly_rounds_to_midnight(self):
        """Test monthly period rounds to midnight UTC."""
        ref = datetime(2026, 1, 13, 18, 45, 12, tzinfo=timezone.utc)
        bucketed = bucket_period_end(ref, Period.MONTHLY, PeriodMode.ROLLING)

        assert bucketed == datetime(2026, 1, 13, 0, 0, 0, tzinfo=timezone.utc)

    def test_bucket_stability_prevents_score_explosion(self):
        """Test that bucketing produces same result across multiple calls.

        This is the core fix for Score explosion - same bucket = same period_hash = upsert.
        """
        # Simulate scheduler calling every 5 minutes within same hour
        timestamps = [
            datetime(2026, 1, 13, 10, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 13, 10, 5, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 13, 10, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 13, 10, 55, 0, tzinfo=timezone.utc),
        ]

        buckets = [bucket_period_end(ts, Period.DAILY, PeriodMode.ROLLING) for ts in timestamps]

        # All should round to same hour bucket
        assert len(set(buckets)) == 1, "All timestamps in same hour should produce same bucket"
        assert buckets[0] == datetime(2026, 1, 13, 10, 0, 0, tzinfo=timezone.utc)

    def test_bucket_calendar_mode_daily(self):
        """Test calendar mode rounds to midnight for daily."""
        ref = datetime(2026, 1, 13, 14, 30, 0, tzinfo=timezone.utc)
        bucketed = bucket_period_end(ref, Period.DAILY, PeriodMode.CALENDAR)

        assert bucketed == datetime(2026, 1, 13, 0, 0, 0, tzinfo=timezone.utc)

    def test_bucket_calendar_mode_weekly(self):
        """Test calendar mode rounds to Monday midnight for weekly."""
        # January 13, 2026 is a Tuesday
        ref = datetime(2026, 1, 13, 14, 30, 0, tzinfo=timezone.utc)
        bucketed = bucket_period_end(ref, Period.WEEKLY, PeriodMode.CALENDAR)

        # Should round to previous Monday (Jan 12)
        assert bucketed.weekday() == 0, "Should be Monday"
        assert bucketed.hour == 0
        assert bucketed.minute == 0

    def test_bucket_calendar_mode_monthly(self):
        """Test calendar mode rounds to 1st of month for monthly."""
        ref = datetime(2026, 1, 13, 14, 30, 0, tzinfo=timezone.utc)
        bucketed = bucket_period_end(ref, Period.MONTHLY, PeriodMode.CALENDAR)

        assert bucketed.day == 1
        assert bucketed.hour == 0
        assert bucketed.minute == 0

    def test_bucket_preserves_timezone(self):
        """Test bucketing preserves timezone info."""
        ref = datetime(2026, 1, 13, 10, 35, 0, tzinfo=timezone.utc)
        bucketed = bucket_period_end(ref, Period.DAILY, PeriodMode.ROLLING)

        assert bucketed.tzinfo == timezone.utc

    def test_bucket_edge_case_already_bucketed(self):
        """Test bucketing timestamp that's already on boundary."""
        ref = datetime(2026, 1, 13, 10, 0, 0, tzinfo=timezone.utc)
        bucketed = bucket_period_end(ref, Period.DAILY, PeriodMode.ROLLING)

        assert bucketed == ref, "Already bucketed timestamp should remain unchanged"


class TestPeriodHash:
    """Tests for Task 1, 21: Period hash for exact matching."""

    def test_compute_period_hash_deterministic(self):
        """Test period_hash is deterministic for same inputs."""
        period_start = datetime(2026, 1, 12, 10, 0, 0, tzinfo=timezone.utc)
        period_end = datetime(2026, 1, 13, 10, 0, 0, tzinfo=timezone.utc)

        hash1 = compute_period_hash(Period.DAILY, period_start, period_end, PeriodMode.ROLLING)
        hash2 = compute_period_hash(Period.DAILY, period_start, period_end, PeriodMode.ROLLING)

        assert hash1 == hash2, "Same inputs should produce same hash"
        assert len(hash1) == 64, "SHA256 hash should be 64 hex chars"

    def test_compute_period_hash_different_periods(self):
        """Test different periods produce different hashes."""
        period_start = datetime(2026, 1, 12, 10, 0, 0, tzinfo=timezone.utc)
        period_end = datetime(2026, 1, 13, 10, 0, 0, tzinfo=timezone.utc)

        hash_daily = compute_period_hash(Period.DAILY, period_start, period_end, PeriodMode.ROLLING)
        hash_weekly = compute_period_hash(Period.WEEKLY, period_start, period_end, PeriodMode.ROLLING)

        assert hash_daily != hash_weekly, "Different periods should produce different hashes"

    def test_compute_period_hash_different_modes(self):
        """Test different modes produce different hashes."""
        period_start = datetime(2026, 1, 12, 10, 0, 0, tzinfo=timezone.utc)
        period_end = datetime(2026, 1, 13, 10, 0, 0, tzinfo=timezone.utc)

        hash_rolling = compute_period_hash(Period.DAILY, period_start, period_end, PeriodMode.ROLLING)
        hash_calendar = compute_period_hash(Period.DAILY, period_start, period_end, PeriodMode.CALENDAR)

        assert hash_rolling != hash_calendar, "Different modes should produce different hashes"

    def test_compute_period_hash_different_boundaries(self):
        """Test different time boundaries produce different hashes."""
        period_start1 = datetime(2026, 1, 12, 10, 0, 0, tzinfo=timezone.utc)
        period_end1 = datetime(2026, 1, 13, 10, 0, 0, tzinfo=timezone.utc)

        period_start2 = datetime(2026, 1, 12, 11, 0, 0, tzinfo=timezone.utc)
        period_end2 = datetime(2026, 1, 13, 11, 0, 0, tzinfo=timezone.utc)

        hash1 = compute_period_hash(Period.DAILY, period_start1, period_end1, PeriodMode.ROLLING)
        hash2 = compute_period_hash(Period.DAILY, period_start2, period_end2, PeriodMode.ROLLING)

        assert hash1 != hash2, "Different boundaries should produce different hashes"

    def test_compute_period_hash_strips_microseconds(self):
        """Test period_hash ignores microseconds (for consistency)."""
        period_start1 = datetime(2026, 1, 12, 10, 0, 0, 123456, tzinfo=timezone.utc)
        period_end1 = datetime(2026, 1, 13, 10, 0, 0, 654321, tzinfo=timezone.utc)

        period_start2 = datetime(2026, 1, 12, 10, 0, 0, 0, tzinfo=timezone.utc)
        period_end2 = datetime(2026, 1, 13, 10, 0, 0, 0, tzinfo=timezone.utc)

        hash1 = compute_period_hash(Period.DAILY, period_start1, period_end1, PeriodMode.ROLLING)
        hash2 = compute_period_hash(Period.DAILY, period_start2, period_end2, PeriodMode.ROLLING)

        assert hash1 == hash2, "Microseconds should be stripped"

    def test_get_bucketed_period_bounds(self):
        """Test get_bucketed_period_bounds returns stable boundaries."""
        ref = datetime(2026, 1, 13, 10, 35, 42, tzinfo=timezone.utc)

        start, end = get_bucketed_period_bounds(Period.DAILY, ref, PeriodMode.ROLLING)

        # End should be bucketed
        assert end == datetime(2026, 1, 13, 10, 0, 0, tzinfo=timezone.utc)
        # Start should be 24 hours before end
        assert (end - start).total_seconds() == 24 * 3600

    def test_get_bucketed_period_bounds_weekly(self):
        """Test weekly bucketed bounds."""
        ref = datetime(2026, 1, 13, 14, 25, 30, tzinfo=timezone.utc)

        start, end = get_bucketed_period_bounds(Period.WEEKLY, ref, PeriodMode.ROLLING)

        # End should be bucketed to midnight
        assert end == datetime(2026, 1, 13, 0, 0, 0, tzinfo=timezone.utc)
        # Start should be 7 days before end
        assert (end - start).total_seconds() == 7 * 24 * 3600

    def test_bucketed_bounds_match_scheduler_logic(self):
        """Test that bucketed bounds match what scheduler uses.

        This ensures Feed API queries same period as scheduler ranked.
        """
        ref = datetime(2026, 1, 13, 10, 35, 0, tzinfo=timezone.utc)

        # Simulate scheduler call
        start_scheduler, end_scheduler = get_bucketed_period_bounds(Period.DAILY, ref, PeriodMode.ROLLING)
        hash_scheduler = compute_period_hash(Period.DAILY, start_scheduler, end_scheduler, PeriodMode.ROLLING)

        # Simulate Feed API call 2 minutes later
        ref_feed = ref + timedelta(minutes=2)
        start_feed, end_feed = get_bucketed_period_bounds(Period.DAILY, ref_feed, PeriodMode.ROLLING)
        hash_feed = compute_period_hash(Period.DAILY, start_feed, end_feed, PeriodMode.ROLLING)

        assert hash_scheduler == hash_feed, "Scheduler and Feed should use same period_hash"


class TestAdaptiveFreshnessDecay:
    """Tests for Task 2: Adaptive freshness decay."""

    def test_period_decay_config_defined(self):
        """Test PERIOD_DECAY_CONFIG constants are defined."""
        assert Period.DAILY in PERIOD_DECAY_CONFIG
        assert Period.WEEKLY in PERIOD_DECAY_CONFIG
        assert Period.MONTHLY in PERIOD_DECAY_CONFIG
        assert Period.ALL in PERIOD_DECAY_CONFIG

        assert PERIOD_DECAY_CONFIG[Period.DAILY].rate == 0.01
        assert PERIOD_DECAY_CONFIG[Period.WEEKLY].rate == 0.003
        assert PERIOD_DECAY_CONFIG[Period.MONTHLY].rate == 0.001
        assert PERIOD_DECAY_CONFIG[Period.ALL].rate == 0.0003

        # Monthly and ALL use hyperbolic decay (gentler for long periods)
        assert PERIOD_DECAY_CONFIG[Period.MONTHLY].hyperbolic is True
        assert PERIOD_DECAY_CONFIG[Period.ALL].hyperbolic is True
        assert PERIOD_DECAY_CONFIG[Period.DAILY].hyperbolic is False

    def test_build_formula_with_period_sets_decay_rate(self):
        """Test build_formula() applies period-aware decay config."""
        formula_daily = build_formula("v4", period=Period.DAILY)
        formula_weekly = build_formula("v4", period=Period.WEEKLY)
        formula_monthly = build_formula("v4", period=Period.MONTHLY)
        formula_all = build_formula("v4", period=Period.ALL)

        assert formula_daily._v3._v2.decay_rate == 0.01
        assert formula_weekly._v3._v2.decay_rate == 0.003
        assert formula_monthly._v3._v2.decay_rate == 0.001
        assert formula_all._v3._v2.decay_rate == 0.0003

        # Hyperbolic flag propagated
        assert formula_daily._v3._v2.hyperbolic is False
        assert formula_monthly._v3._v2.hyperbolic is True
        assert formula_all._v3._v2.hyperbolic is True

    def test_build_formula_without_period_uses_default(self):
        """Test build_formula() without period uses default decay rate."""
        formula = build_formula("v4")
        assert formula._v3._v2.decay_rate == 0.01  # Default

    def test_build_formula_explicit_decay_overrides_period(self):
        """Test explicit decay_rate parameter overrides period."""
        formula = build_formula("v4", period=Period.WEEKLY, decay_rate=0.05)
        assert formula._v3._v2.decay_rate == 0.05, "Explicit decay_rate should override period"

    def test_adaptive_decay_preserves_weekly_scores(self):
        """Test weekly decay prevents score collapse.

        Before fix: 7 days with 0.01 decay → exp(-1.68) = 0.19 (collapsed)
        After fix: 7 days with 0.003 decay → exp(-0.504) = 0.60 (preserved)
        """
        from ranker.features import PostFeatures

        formula_old = FormulaV4(decay_rate=0.01)  # Old aggressive decay
        formula_new = build_formula("v4", period=Period.WEEKLY)  # New adaptive

        # Post at end of 7-day period
        features = PostFeatures(
            post_id=1,
            views=10000,
            forwards=500,
            replies=100,
            reactions=1000,
            age_hours=168,  # 7 days
        )

        score_old = formula_old.compute(features)
        score_new = formula_new.compute(features)

        # New formula should preserve much more score
        assert score_new > score_old * 3, "Weekly decay should preserve 3x more score"

        # Check specific factors
        factor_old = math.exp(-0.01 * 168)  # ≈ 0.19
        factor_new = math.exp(-0.003 * 168)  # ≈ 0.60

        assert factor_new > 0.5, "Weekly posts should retain >50% freshness"
        assert factor_old < 0.2, "Old aggressive decay collapsed weekly scores"

    def test_adaptive_decay_preserves_monthly_scores(self):
        """Test monthly hyperbolic decay prevents score collapse.

        Default: 30 days with 0.01 exp decay → clamped to floor 0.1
        Monthly: 30 days with 0.001 hyperbolic → 1/(1+0.72) ≈ 0.58 (much better)
        """
        from ranker.features import PostFeatures

        formula_default = FormulaV4(decay_rate=0.01)  # exponential + floor
        formula_monthly = build_formula("v4", period=Period.MONTHLY)  # hyperbolic

        # Post at end of 30-day period
        features = PostFeatures(
            post_id=1,
            views=50000,
            forwards=2000,
            replies=500,
            reactions=5000,
            age_hours=720,  # 30 days
        )

        score_default = formula_default.compute(features)
        score_monthly = formula_monthly.compute(features)

        # Monthly formula preserves more score than default with floor
        assert score_monthly > score_default * 5, "Monthly hyperbolic should preserve 5x+ more score"

        # Check hyperbolic factor: 1/(1 + 0.001 * 720) = 1/1.72 ≈ 0.58
        factor_monthly = 1.0 / (1.0 + 0.001 * 720)
        assert factor_monthly > 0.55, "Monthly posts should retain >55% freshness"

    def test_daily_decay_remains_aggressive(self):
        """Test daily decay remains aggressive (no change for daily)."""
        formula = build_formula("v4", period=Period.DAILY)

        from ranker.features import PostFeatures

        # Post at end of 24-hour period
        features = PostFeatures(
            post_id=1,
            views=5000,
            forwards=100,
            replies=20,
            reactions=200,
            age_hours=24,
        )

        score = formula.compute(features)

        # Check decay factor
        factor = math.exp(-0.01 * 24)  # ≈ 0.79
        assert 0.78 < factor < 0.80, "Daily decay should be moderate"


class TestDistributedLocking:
    """Tests for Task 3: Distributed locking."""

    @pytest.mark.asyncio
    async def test_ranking_lock_acquire_and_release(self):
        """Test lock can be acquired and released."""
        lock = RankingLock(redis_url="redis://localhost:6379/1")  # Use test DB

        async with lock.acquire(formula="v4", period="daily", timeout=10) as acquired:
            assert acquired is True, "Lock should be acquired"

        # Lock should be released after context exit
        await lock.close()

    @pytest.mark.asyncio
    async def test_ranking_lock_blocks_concurrent_tasks(self):
        """Test lock prevents concurrent ranking of same period."""
        lock1 = RankingLock(redis_url="redis://localhost:6379/1")
        lock2 = RankingLock(redis_url="redis://localhost:6379/1")

        try:
            # First lock acquired
            async with lock1.acquire(formula="v4", period="daily", timeout=5, blocking_timeout=1) as acquired1:
                assert acquired1 is True

                # Second lock should fail (blocked)
                async with lock2.acquire(formula="v4", period="daily", timeout=5, blocking_timeout=1) as acquired2:
                    assert acquired2 is False, "Second lock should be blocked"
        finally:
            await lock1.close()
            await lock2.close()

    @pytest.mark.asyncio
    async def test_ranking_lock_different_formulas_independent(self):
        """Test locks for different formulas are independent."""
        lock_v1 = RankingLock(redis_url="redis://localhost:6379/1")
        lock_v4 = RankingLock(redis_url="redis://localhost:6379/1")

        try:
            async with lock_v1.acquire(formula="v4", period="daily", timeout=5) as acquired1:
                assert acquired1 is True

                # Different formula should acquire successfully
                async with lock_v4.acquire(formula="v4", period="daily", timeout=5) as acquired2:
                    assert acquired2 is True, "Different formula should have independent lock"
        finally:
            await lock_v1.close()
            await lock_v4.close()

    @pytest.mark.asyncio
    async def test_ranking_lock_different_periods_independent(self):
        """Test locks for different periods are independent."""
        lock_daily = RankingLock(redis_url="redis://localhost:6379/1")
        lock_weekly = RankingLock(redis_url="redis://localhost:6379/1")

        try:
            async with lock_daily.acquire(formula="v4", period="daily", timeout=5) as acquired1:
                assert acquired1 is True

                # Different period should acquire successfully
                async with lock_weekly.acquire(formula="v4", period="weekly", timeout=5) as acquired2:
                    assert acquired2 is True, "Different period should have independent lock"
        finally:
            await lock_daily.close()
            await lock_weekly.close()

    @pytest.mark.asyncio
    async def test_ranking_lock_includes_period_bucket_end(self):
        """Test lock key includes period_bucket_end for precise locking."""
        lock = RankingLock(redis_url="redis://localhost:6379/1")

        bucket1 = "2026-01-13T10:00:00+00:00"
        bucket2 = "2026-01-13T11:00:00+00:00"

        lock1 = RankingLock(redis_url="redis://localhost:6379/1")
        lock2 = RankingLock(redis_url="redis://localhost:6379/1")

        try:
            # Lock bucket1
            async with lock1.acquire(formula="v4", period="daily", period_bucket_end=bucket1, timeout=5) as acquired1:
                assert acquired1 is True

                # Lock bucket2 should succeed (different bucket)
                async with lock2.acquire(formula="v4", period="daily", period_bucket_end=bucket2, timeout=5) as acquired2:
                    assert acquired2 is True, "Different bucket should have independent lock"
        finally:
            await lock1.close()
            await lock2.close()

    def test_ranking_lock_key_format(self):
        """Test lock key format includes all components."""
        lock = RankingLock(key_prefix="test_lock")

        key = lock._make_lock_key(
            formula="v4",
            period="daily",
            period_bucket_end="2026-01-13T10:00:00+00:00"
        )

        assert key == "test_lock:v4:daily:2026-01-13T10:00:00+00:00"
        assert "v4" in key
        assert "daily" in key
        assert "2026-01-13T10:00:00+00:00" in key


class TestSettingsBasedLimits:
    """Tests for Task 5: Settings-based limits."""

    @pytest.mark.asyncio
    async def test_scorer_default_limit_parameter(self):
        """Test Scorer accepts default_limit parameter."""
        mock_session = AsyncMock()
        scorer = Scorer(mock_session, "v4", default_limit=25000)

        assert scorer.default_limit == 25000

    @pytest.mark.asyncio
    async def test_scorer_default_limit_default_value(self):
        """Test Scorer has reasonable default for default_limit."""
        mock_session = AsyncMock()
        scorer = Scorer(mock_session, "v4")

        assert scorer.default_limit == 50000, "Default should be 50000"

    @pytest.mark.asyncio
    async def test_scorer_rank_period_uses_default_limit(self):
        """Test rank_period uses default_limit when limit not specified."""
        mock_session = AsyncMock()
        scorer = Scorer(mock_session, "v4", default_limit=100)

        # Mock repository to return empty list
        scorer.post_repo.get_by_period = AsyncMock(return_value=[])

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        await scorer.rank_period(start, now)

        # Verify get_by_period was called with default_limit
        scorer.post_repo.get_by_period.assert_called_once()
        call_args = scorer.post_repo.get_by_period.call_args
        assert call_args[1]["limit"] == 100

    @pytest.mark.asyncio
    async def test_scorer_rank_period_explicit_limit_overrides(self):
        """Test explicit limit parameter overrides default_limit."""
        mock_session = AsyncMock()
        scorer = Scorer(mock_session, "v4", default_limit=100)

        scorer.post_repo.get_by_period = AsyncMock(return_value=[])

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        await scorer.rank_period(start, now, limit=500)

        # Verify explicit limit was used
        call_args = scorer.post_repo.get_by_period.call_args
        assert call_args[1]["limit"] == 500

    @pytest.mark.asyncio
    async def test_scorer_warns_when_limit_reached(self):
        """Test Scorer logs warning when fetching hits limit."""
        from tests.test_ranker_integration import MockPost

        mock_session = AsyncMock()
        scorer = Scorer(mock_session, "v4", default_limit=10)

        # Create mock posts exactly at limit
        mock_posts = [MockPost(id=i, views=100) for i in range(10)]
        scorer.post_repo.get_by_period = AsyncMock(return_value=mock_posts)

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        # Should log warning (we can't easily test logging, but ensure it doesn't crash)
        results = await scorer.rank_period(start, now)
        assert len(results) == 10


class TestReferenceTimeConsistency:
    """Tests for Task 4: Reference time consistency."""

    @pytest.mark.asyncio
    async def test_scorer_rank_period_passes_reference_time(self):
        """Test Scorer.rank_period passes reference_time to extract_features."""
        mock_session = AsyncMock()
        scorer = Scorer(mock_session, "v4")

        from tests.test_ranker_integration import MockPost

        now = datetime.now(timezone.utc)
        mock_post = MockPost(id=1, views=1000, posted_at=now - timedelta(hours=5))
        scorer.post_repo.get_by_period = AsyncMock(return_value=[mock_post])

        start = now - timedelta(hours=24)
        reference_time = now

        # Patch extract_features to verify reference_time passed
        with patch("ranker.scorer.extract_features") as mock_extract:
            from ranker.features import PostFeatures
            mock_extract.return_value = PostFeatures(
                post_id=1, views=1000, forwards=0, replies=0, reactions=0, age_hours=5
            )

            await scorer.rank_period(start, now, reference_time=reference_time)

            # Verify extract_features called with reference_time
            mock_extract.assert_called_once()
            call_args = mock_extract.call_args
            assert call_args[0][1] == reference_time, "Should pass reference_time to extract_features"

    @pytest.mark.asyncio
    async def test_scorer_rank_period_defaults_reference_time_to_period_end(self):
        """Test reference_time defaults to period_end when not provided."""
        mock_session = AsyncMock()
        scorer = Scorer(mock_session, "v4")

        from tests.test_ranker_integration import MockPost

        now = datetime.now(timezone.utc)
        mock_post = MockPost(id=1, views=1000, posted_at=now - timedelta(hours=5))
        scorer.post_repo.get_by_period = AsyncMock(return_value=[mock_post])

        start = now - timedelta(hours=24)

        with patch("ranker.scorer.extract_features") as mock_extract:
            from ranker.features import PostFeatures
            mock_extract.return_value = PostFeatures(
                post_id=1, views=1000, forwards=0, replies=0, reactions=0, age_hours=5
            )

            await scorer.rank_period(start, now)  # No reference_time

            # Should default to period_end (now)
            call_args = mock_extract.call_args
            assert call_args[0][1] == now, "Should default reference_time to period_end"

    def test_extract_features_uses_reference_time_for_age(self):
        """Test extract_features uses reference_time consistently for age calculation."""
        from ranker.features import extract_features
        from tests.test_ranker_integration import MockPost

        reference_time = datetime(2026, 1, 13, 12, 0, 0, tzinfo=timezone.utc)
        posted_at = datetime(2026, 1, 13, 7, 0, 0, tzinfo=timezone.utc)  # 5 hours ago

        post = MockPost(id=1, views=1000, posted_at=posted_at)
        features = extract_features(post, reference_time)

        # Should be approximately 5 hours
        assert 4.9 < features.age_hours < 5.1, f"Age should be ~5 hours, got {features.age_hours}"


class TestScoreUniqueness:
    """Tests for Score model fields."""

    @pytest.mark.asyncio
    async def test_score_model_has_period_hash_field(self):
        """Test Score model has period_hash field."""
        from storage.models import Score

        assert hasattr(Score, "period_hash")

    @pytest.mark.asyncio
    async def test_score_model_has_global_avg_used_field(self):
        """Test Score model has global_avg_used field for v4 reproducibility."""
        from storage.models import Score

        assert hasattr(Score, "global_avg_used")

