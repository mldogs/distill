"""Novelty scoring module using LLM for information gain analysis."""

from novelty.schemas import NoveltyResult, NoveltyAnalysis
from novelty.config import NoveltyConfig, default_config, PRIMARY_MODEL, FALLBACK_MODEL
from novelty.client import OpenRouterClient
from novelty.analyzer import NoveltyAnalyzer

__all__ = [
    "NoveltyResult",
    "NoveltyAnalysis",
    "NoveltyConfig",
    "default_config",
    "PRIMARY_MODEL",
    "FALLBACK_MODEL",
    "OpenRouterClient",
    "NoveltyAnalyzer",
]
