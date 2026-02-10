"""Scoring formulas for post ranking."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np

from ranker.features import PostFeatures
from ranker.periods import Period


@dataclass
class ScoreResult:
    """Result of scoring a post."""

    post_id: int
    score: float
    explanation: dict[str, Any]

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "post_id": self.post_id,
            "score": self.score,
            "explanation": self.explanation,
        }


class Formula(ABC):
    """Abstract base class for scoring formulas."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Formula version identifier (e.g., 'v0', 'v1')."""
        pass

    @abstractmethod
    def compute(self, features: PostFeatures) -> float:
        """
        Compute score for given features.

        Args:
            features: Extracted post features

        Returns:
            Computed score value
        """
        pass

    @abstractmethod
    def explain(self, features: PostFeatures) -> dict[str, Any]:
        """
        Generate explanation of score components.

        Args:
            features: Extracted post features

        Returns:
            Dictionary with contribution of each component
        """
        pass

    def score(self, features: PostFeatures) -> ScoreResult:
        """
        Compute score with explanation.

        Args:
            features: Extracted post features

        Returns:
            ScoreResult with score and explanation
        """
        return ScoreResult(
            post_id=features.post_id,
            score=self.compute(features),
            explanation=self.explain(features),
        )


class FormulaV2(Formula):
    """
    Channel-relative formula with engagement rate focus.

    Normalizes views and forwards relative to channel's typical performance.
    A post with 10k views from a channel averaging 5k is scored higher than
    a post with 10k views from a channel averaging 50k.

    base = (
        w1 * log(1 + views_ratio) +
        w2 * log(1 + forwards_ratio) +
        w3 * engagement_bonus +
        w4 * log(1 + replies)
    )
    score = base * freshness_factor

    Where:
    - views_ratio = views / channel_avg_views
    - forwards_ratio = forwards / channel_avg_forwards
    - engagement_bonus = min(engagement_rate * 50, 10)
    - freshness_factor: exp(-λt) or 1/(1+λt), with configurable floor

    Falls back to v1-like scoring for channels without statistics.
    """

    DEFAULT_WEIGHTS = {
        "views_ratio": 2.0,
        "forwards_ratio": 3.0,
        "engagement": 1.5,
        "replies": 1.0,
    }
    DEFAULT_DECAY_RATE = 0.01
    DEFAULT_FRESHNESS_FLOOR = 0.1
    # Fallback values for channels without stats
    DEFAULT_AVG_VIEWS = 1000.0
    DEFAULT_AVG_FORWARDS = 10.0

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        decay_rate: float | None = None,
        hyperbolic: bool = False,
        freshness_floor: float | None = None,
    ):
        """
        Initialize formula with optional custom weights.

        Args:
            weights: Dict with keys 'views_ratio', 'forwards_ratio', 'engagement', 'replies'
            decay_rate: Decay rate for freshness (default: 0.01)
            hyperbolic: Use 1/(1+λt) instead of exp(-λt) — gentler for long periods
            freshness_floor: Minimum freshness value (default: 0.1, prevents score zeroing)
        """
        self.weights = {**self.DEFAULT_WEIGHTS, **(weights or {})}
        self.decay_rate = decay_rate if decay_rate is not None else self.DEFAULT_DECAY_RATE
        self.hyperbolic = hyperbolic
        self.freshness_floor = (
            freshness_floor if freshness_floor is not None else self.DEFAULT_FRESHNESS_FLOOR
        )

    @property
    def name(self) -> str:
        return "v2"

    def _get_channel_avg_views(self, features: PostFeatures) -> float:
        """Get channel avg views with fallback."""
        if features.channel_avg_views and features.channel_avg_views > 0:
            return features.channel_avg_views
        return self.DEFAULT_AVG_VIEWS

    def _get_channel_avg_forwards(self, features: PostFeatures) -> float:
        """Get channel avg forwards with fallback."""
        if features.channel_avg_forwards and features.channel_avg_forwards > 0:
            return features.channel_avg_forwards
        return self.DEFAULT_AVG_FORWARDS

    def _compute_engagement_rate(self, features: PostFeatures) -> float:
        """Compute engagement rate (forwards + reactions + replies) / views."""
        views = max(features.views, 100)  # Avoid division by small numbers
        engagement = features.forwards + features.reactions + features.replies
        return engagement / views

    def _compute_freshness_factor(self, age_hours: float) -> float:
        """Compute freshness decay factor (exponential or hyperbolic, with floor)."""
        if self.hyperbolic:
            raw = 1.0 / (1.0 + self.decay_rate * age_hours)
        else:
            raw = float(np.exp(-self.decay_rate * age_hours))
        return max(raw, self.freshness_floor)

    def compute(self, features: PostFeatures) -> float:
        w = self.weights

        # Relative metrics
        channel_avg_views = self._get_channel_avg_views(features)
        channel_avg_forwards = self._get_channel_avg_forwards(features)

        views_ratio = features.views / channel_avg_views
        forwards_ratio = features.forwards / channel_avg_forwards if channel_avg_forwards > 0 else 0

        # Engagement bonus (capped)
        engagement_rate = self._compute_engagement_rate(features)
        engagement_bonus = min(engagement_rate * 50, 10.0)

        # Base score
        base_score = (
            w["views_ratio"] * np.log1p(views_ratio)
            + w["forwards_ratio"] * np.log1p(forwards_ratio)
            + w["engagement"] * engagement_bonus
            + w["replies"] * np.log1p(features.replies)
        )

        freshness_factor = self._compute_freshness_factor(features.age_hours)
        return float(base_score * freshness_factor)

    def explain(self, features: PostFeatures) -> dict[str, Any]:
        w = self.weights

        # Relative metrics
        channel_avg_views = self._get_channel_avg_views(features)
        channel_avg_forwards = self._get_channel_avg_forwards(features)

        views_ratio = features.views / channel_avg_views
        forwards_ratio = features.forwards / channel_avg_forwards if channel_avg_forwards > 0 else 0

        # Engagement
        engagement_rate = self._compute_engagement_rate(features)
        engagement_bonus = min(engagement_rate * 50, 10.0)

        # Individual contributions
        views_contrib = float(w["views_ratio"] * np.log1p(views_ratio))
        forwards_contrib = float(w["forwards_ratio"] * np.log1p(forwards_ratio))
        engagement_contrib = float(w["engagement"] * engagement_bonus)
        replies_contrib = float(w["replies"] * np.log1p(features.replies))

        base_score = views_contrib + forwards_contrib + engagement_contrib + replies_contrib
        freshness_factor = self._compute_freshness_factor(features.age_hours)
        final_score = base_score * freshness_factor

        return {
            "formula": "v2",
            "components": {
                "views_ratio_contribution": views_contrib,
                "forwards_ratio_contribution": forwards_contrib,
                "engagement_contribution": engagement_contrib,
                "replies_contribution": replies_contrib,
                "base_score": base_score,
                "freshness_factor": freshness_factor,
            },
            "inputs": {
                "views": features.views,
                "forwards": features.forwards,
                "reactions": features.reactions,
                "replies": features.replies,
                "age_hours": round(features.age_hours, 2),
                "views_ratio": round(views_ratio, 3),
                "forwards_ratio": round(forwards_ratio, 3),
                "engagement_rate": round(engagement_rate, 4),
                "engagement_bonus": round(engagement_bonus, 2),
            },
            "channel_context": {
                "avg_views": channel_avg_views,
                "avg_forwards": channel_avg_forwards,
                "has_stats": features.channel_avg_views is not None,
            },
            "weights": self.weights,
            "decay_rate": self.decay_rate,
            "decay_type": "hyperbolic" if self.hyperbolic else "exponential",
            "freshness_floor": self.freshness_floor,
            "total": final_score,
        }


class FormulaV3(Formula):
    """
    V2 formula enhanced with LLM-based novelty scoring (additive).

    final_score = v2_score + novelty_weight * novelty_score

    Where:
    - v2_score: Base score from FormulaV2 (channel-relative + engagement + freshness)
    - novelty_score: LLM-computed information gain (0.0 to 1.0)
    - novelty_weight: Additive weight for novelty (default: 5, configurable via env)

    Additive approach: novelty contribution is independent of base score.
    A unique post from a small channel gets the same novelty boost as
    one from a large channel.

    Weight guidelines:
    - 3: Balanced - engagement still matters more than novelty
    - 5: Default - novelty gives significant but not dominant boost
    - 7-10: Novelty-focused - novel content dominates rankings

    Posts without novelty_score are scored as if novelty_score = 0.
    """

    DEFAULT_NOVELTY_WEIGHT = float(os.getenv("NOVELTY_WEIGHT", "5.0"))

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        decay_rate: float | None = None,
        novelty_weight: float | None = None,
        hyperbolic: bool = False,
        freshness_floor: float | None = None,
    ):
        """
        Initialize formula with optional custom parameters.

        Args:
            weights: Dict for v2 formula weights
            decay_rate: Decay rate for freshness
            novelty_weight: Additive weight for novelty (default: 5)
            hyperbolic: Use hyperbolic decay (gentler for long periods)
            freshness_floor: Minimum freshness value (prevents score zeroing)
        """
        self._v2 = FormulaV2(
            weights=weights, decay_rate=decay_rate,
            hyperbolic=hyperbolic, freshness_floor=freshness_floor,
        )
        self.novelty_weight = (
            novelty_weight if novelty_weight is not None else self.DEFAULT_NOVELTY_WEIGHT
        )

    @property
    def name(self) -> str:
        return "v3"

    def _get_novelty_score(self, features: PostFeatures) -> float:
        """Get novelty score, defaulting to 0 if not available."""
        return features.novelty_score if features.novelty_score is not None else 0.0

    def compute(self, features: PostFeatures) -> float:
        v2_score = self._v2.compute(features)
        novelty = self._get_novelty_score(features)
        novelty_contribution = self.novelty_weight * novelty
        return float(v2_score + novelty_contribution)

    def explain(self, features: PostFeatures) -> dict[str, Any]:
        v2_explanation = self._v2.explain(features)
        v2_score = v2_explanation["total"]

        novelty = self._get_novelty_score(features)
        novelty_contribution = self.novelty_weight * novelty
        final_score = v2_score + novelty_contribution

        return {
            "formula": "v3",
            "base_formula": "v2",
            "components": {
                **v2_explanation["components"],
                "v2_score": v2_score,
                "novelty_score": novelty,
                "novelty_contribution": novelty_contribution,
            },
            "inputs": {
                **v2_explanation["inputs"],
                "novelty_score": features.novelty_score,
            },
            "channel_context": v2_explanation.get("channel_context"),
            "weights": {
                **v2_explanation["weights"],
                "novelty_weight": self.novelty_weight,
            },
            "decay_rate": v2_explanation["decay_rate"],
            "decay_type": v2_explanation.get("decay_type", "exponential"),
            "freshness_floor": v2_explanation.get("freshness_floor", 0.1),
            "total": final_score,
        }


class FormulaV4(Formula):
    """
    V3 formula with frequency penalty for spam-heavy channels.

    final_score = v3_score × frequency_penalty

    Where:
    - v3_score: Score from FormulaV3 (v2 + novelty)
    - frequency_penalty: 1 / (1 + log(1 + posts_per_day / avg_posts_per_day))

    Channels posting more frequently than average get penalized:
    - 2 posts/day with avg=5: penalty ≈ 0.85 (slight)
    - 5 posts/day with avg=5: penalty ≈ 0.77 (moderate)
    - 20 posts/day with avg=5: penalty ≈ 0.55 (significant)
    - 50 posts/day with avg=5: penalty ≈ 0.44 (heavy)

    Posts from channels without frequency data use penalty = 1.0 (no penalty).
    """

    DEFAULT_AVG_POSTS_PER_DAY = float(os.getenv("AVG_POSTS_PER_DAY", "5.0"))

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        decay_rate: float | None = None,
        novelty_weight: float | None = None,
        avg_posts_per_day: float | None = None,
        hyperbolic: bool = False,
        freshness_floor: float | None = None,
    ):
        """
        Initialize formula with optional custom parameters.

        Args:
            weights: Dict for v2 formula weights
            decay_rate: Decay rate for freshness
            novelty_weight: Additive weight for novelty
            avg_posts_per_day: Average posts per day baseline (default: 5)
            hyperbolic: Use hyperbolic decay (gentler for long periods)
            freshness_floor: Minimum freshness value (prevents score zeroing)
        """
        self._v3 = FormulaV3(
            weights=weights, decay_rate=decay_rate, novelty_weight=novelty_weight,
            hyperbolic=hyperbolic, freshness_floor=freshness_floor,
        )
        self.avg_posts_per_day = (
            avg_posts_per_day if avg_posts_per_day is not None else self.DEFAULT_AVG_POSTS_PER_DAY
        )

    @property
    def name(self) -> str:
        return "v4"

    def _compute_frequency_penalty(
        self,
        posts_per_day: float | None,
        global_avg: float | None = None,
    ) -> float:
        """
        Compute frequency penalty for spam-heavy channels.

        penalty = 1 / (1 + log(1 + posts_per_day / avg_posts_per_day))

        Args:
            posts_per_day: Channel's posting frequency
            global_avg: Dynamic global average (overrides static default)
        """
        if posts_per_day is None or posts_per_day <= 0:
            return 1.0  # No penalty if no data

        # Use dynamic global average if available, otherwise static default
        avg = global_avg if global_avg and global_avg > 0 else self.avg_posts_per_day
        ratio = posts_per_day / avg
        return float(1.0 / (1.0 + np.log1p(ratio)))

    def compute(self, features: PostFeatures) -> float:
        v3_score = self._v3.compute(features)
        frequency_penalty = self._compute_frequency_penalty(
            features.channel_posts_per_day,
            features.global_avg_posts_per_day,
        )
        return float(v3_score * frequency_penalty)

    def explain(self, features: PostFeatures) -> dict[str, Any]:
        v3_explanation = self._v3.explain(features)
        v3_score = v3_explanation["total"]

        frequency_penalty = self._compute_frequency_penalty(
            features.channel_posts_per_day,
            features.global_avg_posts_per_day,
        )
        final_score = v3_score * frequency_penalty

        # Determine which avg was used
        avg_used = (
            features.global_avg_posts_per_day
            if features.global_avg_posts_per_day and features.global_avg_posts_per_day > 0
            else self.avg_posts_per_day
        )

        return {
            "formula": "v4",
            "base_formula": "v3",
            "components": {
                **v3_explanation["components"],
                "v3_score": v3_score,
                "frequency_penalty": frequency_penalty,
            },
            "inputs": {
                **v3_explanation["inputs"],
                "channel_posts_per_day": features.channel_posts_per_day,
                "global_avg_posts_per_day": features.global_avg_posts_per_day,
            },
            "channel_context": {
                **(v3_explanation.get("channel_context") or {}),
                "posts_per_day": features.channel_posts_per_day,
                "global_avg_posts_per_day": features.global_avg_posts_per_day,
                "avg_posts_per_day_used": avg_used,
            },
            "weights": {
                **v3_explanation["weights"],
            },
            "decay_rate": v3_explanation["decay_rate"],
            "decay_type": v3_explanation.get("decay_type", "exponential"),
            "freshness_floor": v3_explanation.get("freshness_floor", 0.1),
            "total": final_score,
        }


@dataclass
class DecayConfig:
    """Freshness decay configuration per period."""

    rate: float
    hyperbolic: bool = False
    floor: float = 0.1


# Period-aware decay config to prevent score collapse for long periods
PERIOD_DECAY_CONFIG: dict[Period, DecayConfig] = {
    Period.DAILY:   DecayConfig(rate=0.01),                               # exponential, floor 0.1
    Period.WEEKLY:  DecayConfig(rate=0.003),                              # exponential, floor 0.1
    Period.MONTHLY: DecayConfig(rate=0.001, hyperbolic=True),             # hyperbolic, gentler
    Period.ALL:     DecayConfig(rate=0.0003, hyperbolic=True, floor=0.1), # hyperbolic, very gentle
}

# Formula registry (singleton instances with default settings)
_FORMULAS: dict[str, Formula] = {
    "v2": FormulaV2(),
    "v3": FormulaV3(),
    "v4": FormulaV4(),
}


def get_formula(version: str) -> Formula:
    """
    Get formula by version name (singleton instance with defaults).

    For period-aware decay, use build_formula() instead.

    Args:
        version: Formula version ('v2', 'v3', 'v4')

    Returns:
        Formula instance

    Raises:
        ValueError: If unknown version
    """
    if version not in _FORMULAS:
        available = list(_FORMULAS.keys())
        raise ValueError(f"Unknown formula version: {version}. Available: {available}")
    return _FORMULAS[version]


def build_formula(
    version: str,
    period: Period | None = None,
    **kwargs,
) -> Formula:
    """
    Build a new formula instance with custom parameters.

    This factory creates period-aware formulas with adaptive decay rates.
    Use this for scheduled ranking tasks to prevent score collapse on long periods.

    Args:
        version: Formula version ('v2', 'v3', 'v4')
        period: Period type (for adaptive decay rate)
        **kwargs: Additional parameters passed to formula constructor

    Returns:
        New formula instance with custom parameters

    Raises:
        ValueError: If unknown version

    Example:
        formula = build_formula('v4', period=Period.MONTHLY, novelty_weight=7.0)
    """
    # Set period-aware decay config if period provided and not overridden
    if period is not None and "decay_rate" not in kwargs:
        config = PERIOD_DECAY_CONFIG.get(period)
        if config is not None:
            kwargs["decay_rate"] = config.rate
            kwargs.setdefault("hyperbolic", config.hyperbolic)
            kwargs.setdefault("freshness_floor", config.floor)

    if version == "v2":
        return FormulaV2(**kwargs)
    elif version == "v3":
        return FormulaV3(**kwargs)
    elif version == "v4":
        return FormulaV4(**kwargs)
    else:
        available = list(_FORMULAS.keys())
        raise ValueError(f"Unknown formula version: {version}. Available: {available}")


def register_formula(formula: Formula) -> None:
    """
    Register a custom formula.

    Args:
        formula: Formula instance to register
    """
    _FORMULAS[formula.name] = formula


def available_formulas() -> list[str]:
    """Get list of available formula versions."""
    return list(_FORMULAS.keys())
