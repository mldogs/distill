"""Configuration for novelty scoring module."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


# Available models (must support structured output / json_schema)
PRIMARY_MODEL = "openai/gpt-4.1-nano"  # 1M context window
FALLBACK_MODEL = "openai/gpt-4o-mini"


@dataclass
class NoveltyConfig:
    """Configuration for novelty scoring."""

    # API settings
    api_key: Optional[str] = None
    base_url: str = "https://openrouter.ai/api/v1"
    timeout: float = 60.0

    # Models
    primary_model: str = PRIMARY_MODEL
    fallback_model: str = FALLBACK_MODEL

    # Context settings
    context_days: int = 30
    context_max_posts: int = 300
    context_post_max_chars: int = 0  # 0 = no truncation (gpt-4.1-nano has 1M context)

    # Analysis settings
    min_text_length: int = 50
    max_concurrent: int = 5

    # Request identification
    http_referer: str = "https://telegram-post-exchange.local"
    app_title: str = "Telegram Post Exchange"

    @classmethod
    def from_env(cls) -> "NoveltyConfig":
        """Create config from environment variables."""
        return cls(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            primary_model=os.getenv("NOVELTY_PRIMARY_MODEL", PRIMARY_MODEL),
            fallback_model=os.getenv("NOVELTY_FALLBACK_MODEL", FALLBACK_MODEL),
            context_days=int(os.getenv("NOVELTY_CONTEXT_DAYS", "14")),
            max_concurrent=int(os.getenv("NOVELTY_MAX_CONCURRENT", "5")),
            timeout=float(os.getenv("NOVELTY_TIMEOUT", "60.0")),
        )


# Default config instance
default_config = NoveltyConfig.from_env()
