"""OpenRouter API client with structured output support."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from novelty.config import NoveltyConfig, default_config
from novelty.schemas import (
    NoveltyAnalysis, CriteriaScores, NOVELTY_ANALYSIS_SCHEMA, CRITERIA_DEFS,
)

logger = logging.getLogger(__name__)


class OpenRouterError(Exception):
    """Base exception for OpenRouter errors."""
    pass


class OpenRouterRateLimitError(OpenRouterError):
    """Rate limit exceeded."""
    pass


class OpenRouterClient:
    """Client for OpenRouter API with structured output and model fallback."""

    def __init__(
        self,
        config: Optional[NoveltyConfig] = None,
        api_key: Optional[str] = None,
    ):
        self.config = config or default_config
        self.api_key = api_key or self.config.api_key

        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is required")

        self.primary_model = self.config.primary_model
        self.fallback_model = self.config.fallback_model

        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": self.config.http_referer,
                "X-Title": self.config.app_title,
            },
            timeout=self.config.timeout,
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
        retry=retry_if_exception_type((httpx.TimeoutException, OpenRouterRateLimitError)),
    )
    async def _make_request(
        self,
        messages: list[dict[str, str]],
        model: str,
        response_schema: Optional[dict] = None,
    ) -> dict[str, Any]:
        """Make a request to OpenRouter API."""
        payload: dict[str, Any] = {"model": model, "messages": messages}

        if response_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "novelty_analysis",
                    "strict": True,
                    "schema": response_schema,
                },
            }

        logger.debug(f"OpenRouter request to {model}: {len(str(payload))} chars")
        response = await self._client.post("/chat/completions", json=payload)

        if response.status_code == 429:
            raise OpenRouterRateLimitError("Rate limit exceeded")
        if response.status_code != 200:
            error_text = response.text
            logger.error(f"OpenRouter error {response.status_code}: {error_text}")
            raise OpenRouterError(f"API error {response.status_code}: {error_text}")

        return response.json()

    async def analyze_novelty(
        self,
        post_text: str,
        context_posts: list[str],
        channel_name: str,
        use_fallback: bool = True,
    ) -> tuple[NoveltyAnalysis, str, Optional[int]]:
        """Analyze novelty of a post. Returns (analysis, model_used, tokens_used)."""
        messages = self._build_messages(post_text, context_posts, channel_name)

        try:
            result = await self._make_request(
                messages, self.primary_model, NOVELTY_ANALYSIS_SCHEMA
            )
            return self._parse_response(result, self.primary_model)
        except Exception as e:
            logger.warning(f"Primary model {self.primary_model} failed: {e}")
            if not use_fallback:
                raise

        try:
            result = await self._make_request(
                messages, self.fallback_model, NOVELTY_ANALYSIS_SCHEMA
            )
            return self._parse_response(result, self.fallback_model)
        except Exception as e:
            logger.error(f"Fallback model {self.fallback_model} also failed: {e}")
            raise OpenRouterError(f"All models failed: {e}")

    def _build_messages(
        self,
        post_text: str,
        context_posts: list[str],
        channel_name: str,
    ) -> list[dict[str, str]]:
        """Build chat messages for novelty analysis."""
        max_posts = self.config.context_max_posts
        max_chars = self.config.context_post_max_chars

        if context_posts:
            limited = context_posts[:max_posts]
            if max_chars > 0:
                context_summary = "\n".join(
                    f"{i+1}. {t[:max_chars]}..." if len(t) > max_chars else f"{i+1}. {t}"
                    for i, t in enumerate(limited)
                )
            else:
                context_summary = "\n".join(
                    f"{i+1}. {t}" for i, t in enumerate(limited)
                )
        else:
            context_summary = "(No other posts in context)"

        # Build criteria section from CRITERIA_DEFS
        criteria_lines = []
        for i, (name, desc) in enumerate(CRITERIA_DEFS, 1):
            levels = desc.split(", ")
            criteria_lines.append(f"{i}. **{name}**")
            for level in levels:
                criteria_lines.append(f"   - {level}")

        criteria_section = "\n".join(criteria_lines)

        system_prompt = f"""You are a content quality analyzer for a Telegram channel aggregator.

Your task is to evaluate the TARGET POST across 10 criteria, each scored as 0, 0.5, or 1.

## Criteria (score 0 / 0.5 / 1):

{criteria_section}

Compare the TARGET POST against CONTEXT POSTS when evaluating exclusivity and uniqueness.
Respond with JSON matching the required schema."""

        user_prompt = f"""## Context Posts (recent posts from all channels):
{context_summary}

## Target Post to Analyze:
Channel: @{channel_name}
Text: {post_text}

Evaluate this post across all 10 criteria and respond with JSON."""

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _parse_response(
        self,
        response: dict[str, Any],
        model_used: str,
    ) -> tuple[NoveltyAnalysis, str, Optional[int]]:
        """Parse OpenRouter response into NoveltyAnalysis."""
        try:
            choice = response["choices"][0]
            content = choice["message"]["content"]
            data = json.loads(content) if isinstance(content, str) else content
            analysis = NoveltyAnalysis(**data)

            tokens_used = None
            if "usage" in response:
                tokens_used = response["usage"].get("total_tokens")

            return analysis, model_used, tokens_used

        except Exception as e:
            logger.error(f"Failed to parse response: {e}, content: {response}")
            return (
                NoveltyAnalysis(
                    criteria=CriteriaScores.neutral(),
                    reasoning=f"Parse error: {e}",
                    key_insights=[],
                    similar_topics_count=0,
                ),
                model_used,
                None,
            )
