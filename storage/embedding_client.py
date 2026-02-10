"""OpenRouter embedding client for semantic search."""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Base exception for embedding errors."""


class EmbeddingRateLimitError(EmbeddingError):
    """Rate limit exceeded."""


class EmbeddingClient:
    """Async client for OpenRouter embeddings API (BGE-M3)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "baai/bge-m3",
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 30.0,
    ):
        self.model = model
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is required for embedding client")

        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(
            (httpx.TimeoutException, EmbeddingRateLimitError)
        ),
    )
    async def _request(self, texts: list[str]) -> list[list[float]]:
        """Make embedding request to OpenRouter."""
        payload = {"model": self.model, "input": texts}
        response = await self._client.post("/embeddings", json=payload)

        if response.status_code == 429:
            raise EmbeddingRateLimitError("Rate limit exceeded")

        if response.status_code != 200:
            error_text = response.text
            logger.error(f"Embedding API error {response.status_code}: {error_text}")
            raise EmbeddingError(
                f"API error {response.status_code}: {error_text}"
            )

        data = response.json()
        # Sort by index to preserve input order
        sorted_data = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in sorted_data]

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text. Returns vector of floats."""
        results = await self._request([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Returns list of vectors."""
        if not texts:
            return []
        return await self._request(texts)

    @staticmethod
    def compute_text_hash(text: str) -> str:
        """SHA256 hash for change detection."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
