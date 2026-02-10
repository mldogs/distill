"""Collector-specific exceptions for fetch error classification."""

from __future__ import annotations

from dataclasses import dataclass


class FetchError(Exception):
    """Base class for collector fetch errors."""


@dataclass
class FetchTransientError(FetchError):
    """Transient error - safe to retry."""

    message: str
    retry_after: int | None = None

    def __str__(self) -> str:  # pragma: no cover
        if self.retry_after:
            return f"{self.message} (retry_after={self.retry_after}s)"
        return self.message


class FetchPermanentError(FetchError):
    """Permanent error - should not be retried automatically."""

    def __init__(self, message: str, *, reason: str | None = None):
        super().__init__(message)
        self.reason = reason
