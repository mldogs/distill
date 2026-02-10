"""Unit tests for ranker formulas."""

import pytest

from ranker.features import PostFeatures, extract_features_from_dict
from ranker.formulas import (
    FormulaV2,
    FormulaV4,
    ScoreResult,
    available_formulas,
    get_formula,
)
from ranker.periods import Period, get_period_bounds, parse_period


class TestPostFeatures:
    """Tests for PostFeatures extraction."""

    def test_extract_from_dict_basic(self):
        """Test basic feature extraction from dict."""
        data = {
            "id": 123,
            "views": 1000,
            "forwards": 50,
            "replies": 10,
            "reactions_count": 100,
        }
        features = extract_features_from_dict(data)

        assert features.post_id == 123
        assert features.views == 1000
        assert features.forwards == 50
        assert features.replies == 10
        assert features.reactions == 100

    def test_extract_null_values_default_to_zero(self):
        """Test that NULL values are replaced with 0."""
        data = {
            "id": 1,
            "views": None,
            "forwards": None,
            "replies": None,
            "reactions_count": None,
        }
        features = extract_features_from_dict(data)

        assert features.views == 0
        assert features.forwards == 0
        assert features.replies == 0
        assert features.reactions == 0

    def test_extract_missing_keys_default_to_zero(self):
        """Test that missing keys default to 0."""
        data = {"id": 1}
        features = extract_features_from_dict(data)

        assert features.views == 0
        assert features.forwards == 0
        assert features.replies == 0
        assert features.reactions == 0

    def test_features_to_dict(self):
        """Test PostFeatures.to_dict()."""
        features = PostFeatures(
            post_id=1,
            views=100,
            forwards=10,
            replies=5,
            reactions=20,
            age_hours=2.5,
        )
        d = features.to_dict()

        assert d["post_id"] == 1
        assert d["views"] == 100
        assert d["age_hours"] == 2.5


class TestFormulaV2:
    """Tests for channel-relative formula v2."""

    def test_name(self):
        """Test formula name."""
        formula = FormulaV2()
        assert formula.name == "v2"

    def test_default_weights(self):
        """Test default weights are applied."""
        formula = FormulaV2()

        assert formula.weights["views_ratio"] == 2.0
        assert formula.weights["forwards_ratio"] == 3.0
        assert formula.weights["engagement"] == 1.5
        assert formula.weights["replies"] == 1.0
        assert formula.decay_rate == 0.01

    def test_all_features_contribute(self):
        """Test that all features contribute to score."""
        formula = FormulaV2()

        # Base case: only views
        f1 = PostFeatures(post_id=1, views=1000, forwards=0, replies=0, reactions=0, age_hours=0)
        # With forwards
        f2 = PostFeatures(post_id=1, views=1000, forwards=100, replies=0, reactions=0, age_hours=0)
        # With reactions (increases engagement rate)
        f3 = PostFeatures(post_id=1, views=1000, forwards=100, replies=0, reactions=50, age_hours=0)
        # With replies
        f4 = PostFeatures(post_id=1, views=1000, forwards=100, replies=10, reactions=50, age_hours=0)

        s1 = formula.compute(f1)
        s2 = formula.compute(f2)
        s3 = formula.compute(f3)
        s4 = formula.compute(f4)

        assert s2 > s1, "Forwards should increase score"
        assert s3 > s2, "Reactions should increase score"
        assert s4 > s3, "Replies should increase score"

    def test_freshness_decay(self):
        """Test exponential freshness decay."""
        formula = FormulaV2()

        # Same post at different ages
        f_new = PostFeatures(post_id=1, views=1000, forwards=50, replies=5, reactions=20, age_hours=0)
        f_1h = PostFeatures(post_id=1, views=1000, forwards=50, replies=5, reactions=20, age_hours=1)
        f_24h = PostFeatures(post_id=1, views=1000, forwards=50, replies=5, reactions=20, age_hours=24)
        f_168h = PostFeatures(post_id=1, views=1000, forwards=50, replies=5, reactions=20, age_hours=168)

        s_new = formula.compute(f_new)
        s_1h = formula.compute(f_1h)
        s_24h = formula.compute(f_24h)
        s_168h = formula.compute(f_168h)

        assert s_new > s_1h > s_24h > s_168h, "Score should decrease with age"

    def test_freshness_factor_at_zero_age(self):
        """Test freshness factor is 1.0 at age 0."""
        formula = FormulaV2()
        factor = formula._compute_freshness_factor(0)
        assert factor == 1.0

    def test_explanation_format(self):
        """Test explanation contains all components."""
        formula = FormulaV2()
        features = PostFeatures(
            post_id=1,
            views=1000,
            forwards=50,
            replies=10,
            reactions=100,
            age_hours=5.5,
        )

        explanation = formula.explain(features)

        assert explanation["formula"] == "v2"

        # Check components
        components = explanation["components"]
        assert "views_ratio_contribution" in components
        assert "forwards_ratio_contribution" in components
        assert "engagement_contribution" in components
        assert "replies_contribution" in components
        assert "base_score" in components
        assert "freshness_factor" in components

        # Check inputs
        inputs = explanation["inputs"]
        assert inputs["views"] == 1000
        assert inputs["forwards"] == 50
        assert inputs["replies"] == 10
        assert inputs["reactions"] == 100
        assert inputs["age_hours"] == 5.5

        # Check weights included
        assert "weights" in explanation
        assert "decay_rate" in explanation
        assert "total" in explanation

    def test_score_result(self):
        """Test score() returns ScoreResult."""
        formula = FormulaV2()
        features = PostFeatures(
            post_id=42,
            views=500,
            forwards=0,
            replies=0,
            reactions=0,
            age_hours=0,
        )

        result = formula.score(features)

        assert isinstance(result, ScoreResult)
        assert result.post_id == 42
        assert result.score == formula.compute(features)
        assert result.explanation == formula.explain(features)


class TestFormulaRegistry:
    """Tests for formula registry functions."""

    def test_get_formula_v2(self):
        """Test getting v2 formula."""
        formula = get_formula("v2")
        assert isinstance(formula, FormulaV2)
        assert formula.name == "v2"

    def test_get_formula_v4(self):
        """Test getting v4 formula."""
        formula = get_formula("v4")
        assert isinstance(formula, FormulaV4)
        assert formula.name == "v4"

    def test_get_unknown_formula_raises(self):
        """Test getting unknown formula raises ValueError."""
        with pytest.raises(ValueError, match="Unknown formula version"):
            get_formula("v99")

    def test_available_formulas(self):
        """Test available_formulas returns list."""
        formulas = available_formulas()
        assert "v2" in formulas
        assert "v3" in formulas
        assert "v4" in formulas


class TestPeriods:
    """Tests for period utilities."""

    def test_parse_period_aliases(self):
        """Test parsing period aliases."""
        assert parse_period("24h") == Period.DAILY
        assert parse_period("daily") == Period.DAILY
        assert parse_period("7d") == Period.WEEKLY
        assert parse_period("weekly") == Period.WEEKLY
        assert parse_period("30d") == Period.MONTHLY
        assert parse_period("monthly") == Period.MONTHLY

    def test_parse_period_case_insensitive(self):
        """Test parsing is case insensitive."""
        assert parse_period("DAILY") == Period.DAILY
        assert parse_period("Weekly") == Period.WEEKLY

    def test_parse_unknown_period_raises(self):
        """Test parsing unknown period raises ValueError."""
        with pytest.raises(ValueError, match="Unknown period"):
            parse_period("1y")

    def test_period_hours(self):
        """Test period hours property."""
        assert Period.DAILY.hours == 24
        assert Period.WEEKLY.hours == 24 * 7
        assert Period.MONTHLY.hours == 24 * 30

    def test_get_period_bounds(self):
        """Test get_period_bounds returns correct range."""
        from datetime import datetime, timezone

        ref = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)

        start, end = get_period_bounds(Period.DAILY, ref)
        assert end == ref
        assert (end - start).total_seconds() == 24 * 3600

        start, end = get_period_bounds(Period.WEEKLY, ref)
        assert end == ref
        assert (end - start).total_seconds() == 7 * 24 * 3600


class TestScoreResult:
    """Tests for ScoreResult dataclass."""

    def test_to_dict(self):
        """Test ScoreResult.to_dict()."""
        result = ScoreResult(
            post_id=123,
            score=45.67,
            explanation={"formula": "v4", "total": 45.67},
        )

        d = result.to_dict()

        assert d["post_id"] == 123
        assert d["score"] == 45.67
        assert d["explanation"]["formula"] == "v4"
