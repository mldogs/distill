"""Unit tests for novelty scoring module."""

import pytest
from pydantic import ValidationError

from novelty.schemas import (
    CriteriaScores, NoveltyAnalysis, NoveltyResult,
    NOVELTY_ANALYSIS_SCHEMA, NOVELTY_CRITERIA,
)
from ranker.features import PostFeatures, extract_features_from_dict
from ranker.formulas import FormulaV2, FormulaV3, get_formula, available_formulas


def _make_criteria(**overrides: float) -> CriteriaScores:
    """Create CriteriaScores with all-0.5 defaults and optional overrides."""
    vals = {c: 0.5 for c in NOVELTY_CRITERIA}
    vals.update(overrides)
    return CriteriaScores(**vals)


class TestNoveltyAnalysis:
    """Tests for NoveltyAnalysis schema."""

    def test_valid_analysis(self):
        """Test creating a valid NoveltyAnalysis."""
        criteria = _make_criteria(exclusivity=1.0, depth=1.0)
        analysis = NoveltyAnalysis(
            criteria=criteria,
            reasoning="This post introduces a new perspective on AI development.",
            key_insights=["New API release", "Performance improvements"],
            similar_topics_count=2,
        )
        assert 0.0 <= analysis.novelty_score <= 1.0
        assert "perspective" in analysis.reasoning
        assert len(analysis.key_insights) == 2
        assert analysis.similar_topics_count == 2

    def test_score_bounds(self):
        """Test that criteria scores must be between 0 and 1."""
        with pytest.raises(ValidationError):
            CriteriaScores(**{c: 1.5 if c == "exclusivity" else 0.5 for c in NOVELTY_CRITERIA})

        with pytest.raises(ValidationError):
            CriteriaScores(**{c: -0.1 if c == "exclusivity" else 0.5 for c in NOVELTY_CRITERIA})

    def test_defaults(self):
        """Test default values."""
        analysis = NoveltyAnalysis(
            criteria=CriteriaScores.neutral(),
            reasoning="Test",
        )
        assert analysis.key_insights == []
        assert analysis.similar_topics_count == 0
        assert analysis.novelty_score == pytest.approx(0.5)

    def test_reasoning_required(self):
        """Test that reasoning is required."""
        with pytest.raises(ValidationError):
            NoveltyAnalysis(
                criteria=CriteriaScores.neutral(),
            )


class TestNoveltyResult:
    """Tests for NoveltyResult schema."""

    def test_valid_result(self):
        """Test creating a valid NoveltyResult."""
        criteria = _make_criteria()
        analysis = NoveltyAnalysis(
            criteria=criteria,
            reasoning="Unique content found",
            key_insights=["Insight 1"],
        )
        result = NoveltyResult(
            post_id=123,
            novelty_score=0.75,
            criteria_scores=criteria,
            analysis=analysis,
            model_used="google/gemini-2.0-flash-001",
            tokens_used=150,
            cost_usd=0.0001,
        )
        assert result.post_id == 123
        assert result.novelty_score == 0.75
        assert result.model_used == "google/gemini-2.0-flash-001"

    def test_to_dict(self):
        """Test to_dict conversion for storage."""
        criteria = _make_criteria()
        analysis = NoveltyAnalysis(
            criteria=criteria,
            reasoning="Novel analysis",
            key_insights=["Key 1", "Key 2"],
            similar_topics_count=3,
        )
        result = NoveltyResult(
            post_id=456,
            novelty_score=0.8,
            criteria_scores=criteria,
            analysis=analysis,
            model_used="test-model",
            tokens_used=100,
            cost_usd=0.05,
        )
        d = result.to_dict()

        assert d["post_id"] == 456
        assert d["novelty_score"] == 0.8
        assert d["reasoning"] == "Novel analysis"
        assert d["key_insights"] == ["Key 1", "Key 2"]
        assert d["similar_topics_count"] == 3
        assert d["model_used"] == "test-model"
        assert d["tokens_used"] == 100
        assert d["cost_usd"] == 0.05
        assert "criteria" in d


class TestNoveltyAnalysisSchema:
    """Tests for JSON schema for OpenRouter structured output."""

    def test_schema_structure(self):
        """Test that schema has correct structure."""
        assert NOVELTY_ANALYSIS_SCHEMA["type"] == "object"
        assert "criteria" in NOVELTY_ANALYSIS_SCHEMA["properties"]
        assert "reasoning" in NOVELTY_ANALYSIS_SCHEMA["properties"]
        assert "key_insights" in NOVELTY_ANALYSIS_SCHEMA["properties"]
        assert "similar_topics_count" in NOVELTY_ANALYSIS_SCHEMA["properties"]

    def test_required_fields(self):
        """Test that required fields are specified."""
        assert "criteria" in NOVELTY_ANALYSIS_SCHEMA["required"]
        assert "reasoning" in NOVELTY_ANALYSIS_SCHEMA["required"]

    def test_score_constraints(self):
        """Test criteria score constraints in schema."""
        criteria_schema = NOVELTY_ANALYSIS_SCHEMA["properties"]["criteria"]
        assert criteria_schema["type"] == "object"
        # Each criterion should allow 0, 0.5, 1
        for name in NOVELTY_CRITERIA:
            assert name in criteria_schema["properties"]
            assert criteria_schema["properties"][name]["enum"] == [0, 0.5, 1]


class TestFormulaV3:
    """Tests for FormulaV3 with novelty scoring."""

    def test_name(self):
        """Test formula name."""
        formula = FormulaV3()
        assert formula.name == "v3"

    def test_registered(self):
        """Test V3 is in available formulas."""
        assert "v3" in available_formulas()
        formula = get_formula("v3")
        assert formula.name == "v3"

    def test_score_without_novelty(self):
        """Test score when novelty_score is None (V3 = V2 + 0)."""
        formula = FormulaV3()
        features = PostFeatures(
            post_id=1,
            views=1000,
            forwards=10,
            replies=5,
            reactions=50,
            age_hours=24,
            novelty_score=None,
        )
        result = formula.score(features)

        # Without novelty, V3 should equal V2
        v2 = FormulaV2()
        v2_result = v2.score(features)

        assert result.score == pytest.approx(v2_result.score, rel=1e-6)

    def test_score_with_novelty(self):
        """Test score boost with novelty_score (additive)."""
        formula = FormulaV3()
        features = PostFeatures(
            post_id=1,
            views=1000,
            forwards=10,
            replies=5,
            reactions=50,
            age_hours=24,
            novelty_score=1.0,
        )
        result = formula.score(features)

        # V3 = V2 + novelty_weight * novelty_score
        v2 = FormulaV2()
        v2_result = v2.score(features)

        expected = v2_result.score + FormulaV3.DEFAULT_NOVELTY_WEIGHT * 1.0
        assert result.score == pytest.approx(expected, rel=1e-6)

    def test_partial_novelty(self):
        """Test score with partial novelty_score."""
        formula = FormulaV3()
        features = PostFeatures(
            post_id=1,
            views=1000,
            forwards=10,
            replies=5,
            reactions=50,
            age_hours=24,
            novelty_score=0.5,
        )
        result = formula.score(features)

        v2 = FormulaV2()
        v2_result = v2.score(features)

        expected = v2_result.score + FormulaV3.DEFAULT_NOVELTY_WEIGHT * 0.5
        assert result.score == pytest.approx(expected, rel=1e-6)

    def test_custom_novelty_weight(self):
        """Test custom novelty_weight parameter."""
        formula = FormulaV3(novelty_weight=10.0)
        features = PostFeatures(
            post_id=1,
            views=1000,
            forwards=10,
            replies=5,
            reactions=50,
            age_hours=24,
            novelty_score=1.0,
        )
        result = formula.score(features)

        v2 = FormulaV2()
        v2_result = v2.score(features)

        expected = v2_result.score + 10.0 * 1.0
        assert result.score == pytest.approx(expected, rel=1e-6)

    def test_explanation_includes_novelty(self):
        """Test that explanation includes novelty components."""
        formula = FormulaV3()
        features = PostFeatures(
            post_id=1,
            views=1000,
            forwards=10,
            replies=5,
            reactions=50,
            age_hours=24,
            novelty_score=0.8,
        )
        result = formula.score(features)

        assert result.explanation["formula"] == "v3"
        assert "novelty_score" in result.explanation["components"]
        assert "novelty_contribution" in result.explanation["components"]
        assert result.explanation["components"]["novelty_score"] == 0.8
        assert "novelty_weight" in result.explanation["weights"]

    def test_explanation_none_novelty(self):
        """Test explanation when novelty is None."""
        formula = FormulaV3()
        features = PostFeatures(
            post_id=1,
            views=1000,
            forwards=10,
            replies=5,
            reactions=50,
            age_hours=24,
            novelty_score=None,
        )
        result = formula.score(features)

        assert result.explanation["components"]["novelty_score"] == 0.0
        assert result.explanation["components"]["novelty_contribution"] == 0.0
        assert result.explanation["inputs"]["novelty_score"] is None


class TestPostFeaturesWithNovelty:
    """Tests for PostFeatures with novelty_score field."""

    def test_novelty_default_none(self):
        """Test that novelty_score defaults to None."""
        features = PostFeatures(
            post_id=1,
            views=100,
            forwards=10,
            replies=5,
            reactions=20,
            age_hours=2.5,
        )
        assert features.novelty_score is None

    def test_novelty_explicit(self):
        """Test setting novelty_score explicitly."""
        features = PostFeatures(
            post_id=1,
            views=100,
            forwards=10,
            replies=5,
            reactions=20,
            age_hours=2.5,
            novelty_score=0.75,
        )
        assert features.novelty_score == 0.75

    def test_extract_from_dict_with_novelty(self):
        """Test extraction from dict with novelty_score."""
        data = {
            "id": 123,
            "views": 1000,
            "forwards": 50,
            "replies": 10,
            "reactions_count": 100,
            "novelty_score": 0.9,
        }
        features = extract_features_from_dict(data)

        assert features.novelty_score == 0.9

    def test_extract_from_dict_without_novelty(self):
        """Test extraction from dict without novelty_score."""
        data = {
            "id": 123,
            "views": 1000,
        }
        features = extract_features_from_dict(data)

        assert features.novelty_score is None

    def test_to_dict_includes_novelty(self):
        """Test that to_dict includes novelty_score."""
        features = PostFeatures(
            post_id=1,
            views=100,
            forwards=10,
            replies=5,
            reactions=20,
            age_hours=2.5,
            novelty_score=0.65,
        )
        d = features.to_dict()

        assert "novelty_score" in d
        assert d["novelty_score"] == 0.65
