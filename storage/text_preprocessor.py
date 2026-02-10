"""Text preprocessing for search indexing."""

from __future__ import annotations

import html
import re


class TextPreprocessor:
    """Clean and normalize text for FTS and embedding pipelines."""

    _RE_URL = re.compile(r"https?://\S+")
    _RE_MENTION = re.compile(r"@\w+")
    _RE_WHITESPACE = re.compile(r"\s+")
    _RE_CYRILLIC = re.compile(r"[\u0400-\u04FF]")

    @classmethod
    def clean_for_fts(cls, text: str | None) -> str:
        """Strip HTML entities, URLs, @mentions. Normalize whitespace."""
        if not text:
            return ""
        result = html.unescape(text)
        result = cls._RE_URL.sub("", result)
        result = cls._RE_MENTION.sub("", result)
        result = cls._RE_WHITESPACE.sub(" ", result).strip()
        return result

    @classmethod
    def clean_for_embedding(cls, text: str | None) -> str:
        """Strip HTML/URLs but keep @mentions and #hashtags (semantic signal)."""
        if not text:
            return ""
        result = html.unescape(text)
        result = cls._RE_URL.sub("", result)
        result = cls._RE_WHITESPACE.sub(" ", result).strip()
        return result

    @classmethod
    def has_cyrillic(cls, text: str | None) -> bool:
        """Check if text contains Cyrillic characters."""
        if not text:
            return False
        return bool(cls._RE_CYRILLIC.search(text))
