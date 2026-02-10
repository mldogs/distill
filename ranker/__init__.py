"""
Ranker module for scoring Telegram posts.

Production formula: v4 (channel-relative + novelty + frequency penalty).
"""

from ranker.features import PostFeatures, extract_features, extract_features_from_dict
from ranker.formulas import (
    Formula,
    ScoreResult,
    available_formulas,
    get_formula,
    register_formula,
)
from ranker.periods import Period, get_period_bounds, get_period_bounds_from_dates, parse_period
from ranker.scorer import Scorer, score_posts_sync

__all__ = [
    "Scorer",
    "Formula",
    "ScoreResult",
    "PostFeatures",
    "Period",
    "get_formula",
    "available_formulas",
    "register_formula",
    "extract_features",
    "extract_features_from_dict",
    "get_period_bounds",
    "get_period_bounds_from_dates",
    "parse_period",
    "score_posts_sync",
]
