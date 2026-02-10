"""Integration tests for ranker module."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ranker import Scorer, get_formula, score_posts_sync
from ranker.features import extract_features
from ranker.periods import Period


class MockPost:
    """Mock Post object for testing without database."""

    def __init__(
        self,
        id: int,
        views: int = 0,
        forwards: int = 0,
        replies: int = 0,
        reactions_count: int = 0,
        posted_at: datetime | None = None,
        novelty_score: float | None = None,
    ):
        self.id = id
        self.views = views
        self.forwards = forwards
        self.replies = replies
        self.reactions_count = reactions_count
        self.posted_at = posted_at or datetime.now(timezone.utc)
        self.novelty_score = novelty_score


class TestScorePostsSync:
    """Tests for synchronous scoring utility."""

    def test_score_single_post(self):
        """Test scoring a single post."""
        post = MockPost(id=1, views=1000, forwards=50, replies=10, reactions_count=100)
        results = score_posts_sync([post], "v4")

        assert len(results) == 1
        assert results[0].post_id == 1
        assert results[0].score > 0

    def test_score_multiple_posts_sorted(self):
        """Test that results are sorted by score descending."""
        posts = [
            MockPost(id=1, views=100),
            MockPost(id=2, views=10000),
            MockPost(id=3, views=1000),
        ]
        results = score_posts_sync(posts, "v2")

        assert len(results) == 3
        # Should be sorted by score descending
        assert results[0].post_id == 2  # highest views
        assert results[1].post_id == 3
        assert results[2].post_id == 1  # lowest views

    def test_score_with_formula_instance(self):
        """Test scoring with Formula instance instead of string."""
        formula = get_formula("v4")
        post = MockPost(id=1, views=1000)
        results = score_posts_sync([post], formula)

        assert len(results) == 1
        assert results[0].explanation["formula"] == "v4"

    def test_score_empty_list(self):
        """Test scoring empty list."""
        results = score_posts_sync([], "v2")
        assert results == []

    def test_v2_considers_engagement(self):
        """Test that v2 considers engagement metrics, not just views."""
        # Post A: high views, low engagement
        post_a = MockPost(id=1, views=10000, forwards=0, replies=0, reactions_count=0)
        # Post B: lower views, high engagement
        post_b = MockPost(id=2, views=5000, forwards=500, replies=100, reactions_count=1000)

        # v2 should rank B higher (engagement matters)
        results_v2 = score_posts_sync([post_a, post_b], "v2")
        assert results_v2[0].post_id == 2, "v2 should consider engagement"

    def test_freshness_affects_ranking(self):
        """Test that fresher posts rank higher with v4."""
        now = datetime.now(timezone.utc)

        # Same metrics, different ages
        post_new = MockPost(id=1, views=1000, posted_at=now)
        post_old = MockPost(id=2, views=1000, posted_at=now - timedelta(days=7))

        results = score_posts_sync([post_old, post_new], "v4", reference_time=now)

        assert results[0].post_id == 1, "Newer post should rank higher"
        assert results[0].score > results[1].score


class TestExtractFeatures:
    """Tests for feature extraction from Post objects."""

    def test_extract_from_mock_post(self):
        """Test feature extraction from mock post."""
        now = datetime.now(timezone.utc)
        posted = now - timedelta(hours=5)

        post = MockPost(
            id=42,
            views=1000,
            forwards=50,
            replies=10,
            reactions_count=100,
            posted_at=posted,
        )

        features = extract_features(post, now)

        assert features.post_id == 42
        assert features.views == 1000
        assert features.forwards == 50
        assert features.replies == 10
        assert features.reactions == 100
        assert 4.9 < features.age_hours < 5.1  # approximately 5 hours

    def test_extract_null_fields(self):
        """Test extraction with None fields."""
        post = MockPost(id=1)
        post.views = None
        post.forwards = None
        post.replies = None
        post.reactions_count = None

        features = extract_features(post)

        assert features.views == 0
        assert features.forwards == 0
        assert features.replies == 0
        assert features.reactions == 0


class TestScorerWithMocks:
    """Tests for Scorer class using mocks."""

    @pytest.fixture
    def mock_session(self):
        """Create mock async session."""
        return AsyncMock()

    @pytest.fixture
    def mock_posts(self):
        """Create sample mock posts."""
        now = datetime.now(timezone.utc)
        return [
            MockPost(id=1, views=5000, forwards=100, replies=20, reactions_count=200, posted_at=now - timedelta(hours=2)),
            MockPost(id=2, views=10000, forwards=50, replies=5, reactions_count=100, posted_at=now - timedelta(hours=12)),
            MockPost(id=3, views=3000, forwards=200, replies=50, reactions_count=500, posted_at=now - timedelta(hours=1)),
        ]

    @pytest.mark.asyncio
    async def test_scorer_computes_scores(self, mock_session, mock_posts):
        """Test Scorer._compute_scores method."""
        scorer = Scorer(mock_session, "v4")

        results = scorer._compute_scores(mock_posts)

        assert len(results) == 3
        # All posts should have scores
        for result in results:
            assert result.score > 0
            assert result.explanation is not None

    @pytest.mark.asyncio
    async def test_scorer_rank_period(self, mock_session, mock_posts):
        """Test Scorer.rank_period with mocked repository."""
        scorer = Scorer(mock_session, "v4")

        # Mock the repository method
        scorer.post_repo.get_by_period = AsyncMock(return_value=mock_posts)

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        results = await scorer.rank_period(start, now)

        assert len(results) == 3
        # Results should be sorted by score descending
        assert results[0].score >= results[1].score >= results[2].score

    @pytest.mark.asyncio
    async def test_scorer_save_scores(self, mock_session, mock_posts):
        """Test Scorer.save_scores calls repository."""
        scorer = Scorer(mock_session, "v4")

        # Mock bulk_upsert_scores
        scorer.score_repo.bulk_upsert_scores = AsyncMock(return_value=3)

        # Compute some scores
        results = scorer._compute_scores(mock_posts)

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        saved_count = await scorer.save_scores(results, start, now)

        assert saved_count == 3
        scorer.score_repo.bulk_upsert_scores.assert_called_once()

        # Check the data passed to repository
        call_args = scorer.score_repo.bulk_upsert_scores.call_args[0][0]
        assert len(call_args) == 3
        assert all("post_id" in item for item in call_args)
        assert all("score" in item for item in call_args)
        assert all("formula_version" in item for item in call_args)
        assert all(item["formula_version"] == "v4" for item in call_args)

    @pytest.mark.asyncio
    async def test_scorer_rank_and_save(self, mock_session, mock_posts):
        """Test Scorer.rank_and_save combines ranking and saving."""
        scorer = Scorer(mock_session, "v4")

        # Mock repository methods
        scorer.post_repo.get_by_period = AsyncMock(return_value=mock_posts)
        scorer.score_repo.bulk_upsert_scores = AsyncMock(return_value=3)

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        scores, saved_count = await scorer.rank_and_save(start, now)

        assert len(scores) == 3
        assert saved_count == 3

    @pytest.mark.asyncio
    async def test_scorer_with_empty_posts(self, mock_session):
        """Test Scorer handles empty post list."""
        scorer = Scorer(mock_session, "v2")
        scorer.post_repo.get_by_period = AsyncMock(return_value=[])

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        results = await scorer.rank_period(start, now)
        assert results == []

    @pytest.mark.asyncio
    async def test_scorer_save_empty_scores(self, mock_session):
        """Test Scorer.save_scores with empty list."""
        scorer = Scorer(mock_session, "v4")

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        saved_count = await scorer.save_scores([], start, now)
        assert saved_count == 0


class TestExplanationQuality:
    """Tests for explanation quality and completeness."""

    def test_v4_explanation_has_all_components(self):
        """Test v4 explanation includes all score components."""
        post = MockPost(
            id=1,
            views=1000,
            forwards=50,
            replies=10,
            reactions_count=100,
            posted_at=datetime.now(timezone.utc) - timedelta(hours=5),
        )

        results = score_posts_sync([post], "v4")
        explanation = results[0].explanation

        # Required keys
        assert "formula" in explanation
        assert "components" in explanation
        assert "inputs" in explanation
        assert "weights" in explanation
        assert "decay_rate" in explanation
        assert "total" in explanation

        # Component breakdown (v4 uses v2-based components)
        components = explanation["components"]
        assert "views_ratio_contribution" in components
        assert "forwards_ratio_contribution" in components
        assert "engagement_contribution" in components
        assert "replies_contribution" in components
        assert "base_score" in components
        assert "freshness_factor" in components
        assert "frequency_penalty" in components

        # Verify total matches score
        assert explanation["total"] == results[0].score

    def test_explanation_inputs_match_post(self):
        """Test explanation inputs match actual post values."""
        post = MockPost(
            id=1,
            views=1234,
            forwards=56,
            replies=78,
            reactions_count=90,
        )

        results = score_posts_sync([post], "v4")
        inputs = results[0].explanation["inputs"]

        assert inputs["views"] == 1234
        assert inputs["forwards"] == 56
        assert inputs["replies"] == 78
        assert inputs["reactions"] == 90
