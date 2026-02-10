"""Integration tests for novelty scoring with real OpenRouter API.

These tests require OPENROUTER_API_KEY environment variable.
Run with: pytest tests/test_novelty_integration.py -v
"""

import os
import pytest

from novelty import NoveltyConfig, OpenRouterClient, NoveltyAnalyzer, PRIMARY_MODEL, FALLBACK_MODEL
from novelty.schemas import NoveltyAnalysis

# Skip all tests if no API key
pytestmark = pytest.mark.skipif(
    not os.getenv("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set"
)


@pytest.fixture
def api_key():
    """Get API key from environment."""
    return os.getenv("OPENROUTER_API_KEY")


@pytest.fixture
def config(api_key):
    """Create test config with real API key."""
    return NoveltyConfig(
        api_key=api_key,
        primary_model=PRIMARY_MODEL,
        fallback_model=FALLBACK_MODEL,
        context_max_posts=10,
        context_post_max_chars=0,  # No truncation
    )


class TestOpenRouterClient:
    """Integration tests for OpenRouterClient."""

    @pytest.mark.asyncio
    async def test_simple_novelty_analysis(self, config):
        """Test basic novelty analysis with real API."""
        async with OpenRouterClient(config=config) as client:
            analysis, model_used, tokens_used = await client.analyze_novelty(
                post_text="Breaking: New AI model achieves 99% accuracy on benchmark XYZ, surpassing all previous models by 15 percentage points.",
                context_posts=[
                    "AI models continue to improve in 2024",
                    "Machine learning benchmarks are evolving",
                    "Tech companies invest in AI research",
                ],
                channel_name="tech_news",
            )

            assert isinstance(analysis, NoveltyAnalysis)
            assert 0.0 <= analysis.novelty_score <= 1.0
            assert len(analysis.reasoning) > 0
            assert "/" in model_used  # model IDs are in "provider/model" format
            assert tokens_used is None or tokens_used > 0

    @pytest.mark.asyncio
    async def test_duplicate_detection(self, config):
        """Test that duplicates get low novelty score."""
        duplicate_text = "Bitcoin price reached $100,000 today"
        context = [
            "Bitcoin price reached $100,000 today, marking a new all-time high",
            "BTC hits $100K milestone",
            "Cryptocurrency market celebrates as Bitcoin crosses $100,000",
        ]

        async with OpenRouterClient(config=config) as client:
            analysis, _, _ = await client.analyze_novelty(
                post_text=duplicate_text,
                context_posts=context,
                channel_name="crypto_news",
            )

            # Duplicate content should have low novelty
            assert analysis.novelty_score < 0.5
            assert analysis.similar_topics_count >= 1

    @pytest.mark.asyncio
    async def test_unique_content_detection(self, config):
        """Test that unique content gets high novelty score."""
        unique_text = """Exclusive: Internal documents reveal that Company X
        has been secretly developing a quantum computing chip that operates
        at room temperature. Sources say the breakthrough could revolutionize
        the industry within 2 years."""

        context = [
            "Tech stocks rise on positive earnings",
            "New smartphone released by Samsung",
            "Cloud computing market grows 20%",
        ]

        async with OpenRouterClient(config=config) as client:
            analysis, _, _ = await client.analyze_novelty(
                post_text=unique_text,
                context_posts=context,
                channel_name="tech_insider",
            )

            # Unique exclusive news should have higher novelty
            assert analysis.novelty_score > 0.5
            assert len(analysis.key_insights) > 0

    @pytest.mark.asyncio
    async def test_empty_context(self, config):
        """Test analysis with empty context."""
        async with OpenRouterClient(config=config) as client:
            analysis, _, _ = await client.analyze_novelty(
                post_text="Apple announced a new M5 chip today with 40% better performance and 50% lower power consumption. The chip will ship in MacBook Pro models starting next month at the same price point.",
                context_posts=[],
                channel_name="test_channel",
            )

            assert isinstance(analysis, NoveltyAnalysis)
            assert 0.0 <= analysis.novelty_score <= 1.0

    @pytest.mark.asyncio
    async def test_russian_text(self, config):
        """Test analysis of Russian language content."""
        async with OpenRouterClient(config=config) as client:
            analysis, _, _ = await client.analyze_novelty(
                post_text="Эксклюзив: Центробанк готовит новые меры по регулированию криптовалют в России",
                context_posts=[
                    "Новости экономики России",
                    "Курс рубля стабилен",
                    "Инфляция замедляется",
                ],
                channel_name="economics_ru",
            )

            assert isinstance(analysis, NoveltyAnalysis)
            assert 0.0 <= analysis.novelty_score <= 1.0
            assert len(analysis.reasoning) > 0

    @pytest.mark.asyncio
    async def test_fallback_model(self, api_key):
        """Test that fallback model works when primary fails."""
        # Use invalid primary model to trigger fallback
        config = NoveltyConfig(
            api_key=api_key,
            primary_model="invalid/nonexistent-model",
            fallback_model=PRIMARY_MODEL,
        )

        async with OpenRouterClient(config=config) as client:
            analysis, model_used, _ = await client.analyze_novelty(
                post_text="Test content for fallback",
                context_posts=["Context post"],
                channel_name="test",
            )

            assert isinstance(analysis, NoveltyAnalysis)
            # Should have used fallback model
            assert model_used == PRIMARY_MODEL


class TestNoveltyConfig:
    """Tests for NoveltyConfig."""

    def test_config_from_env(self, api_key):
        """Test creating config from environment."""
        os.environ["OPENROUTER_API_KEY"] = api_key
        config = NoveltyConfig.from_env()

        assert config.api_key == api_key
        assert config.primary_model == PRIMARY_MODEL

    def test_custom_config(self, api_key):
        """Test custom config values."""
        config = NoveltyConfig(
            api_key=api_key,
            context_days=7,
            context_max_posts=25,
            context_post_max_chars=150,
            max_concurrent=3,
        )

        assert config.context_days == 7
        assert config.context_max_posts == 25
        assert config.context_post_max_chars == 150
        assert config.max_concurrent == 3


class TestModels:
    """Test different model configurations."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("model_id", [PRIMARY_MODEL, FALLBACK_MODEL])
    async def test_model_availability(self, api_key, model_id):
        """Test that configured models are available and working."""
        config = NoveltyConfig(
            api_key=api_key,
            primary_model=model_id,
        )

        async with OpenRouterClient(config=config) as client:
            analysis, model_used, _ = await client.analyze_novelty(
                post_text="Test content for model availability check",
                context_posts=["Some context"],
                channel_name="test",
                use_fallback=False,  # Don't fallback, test specific model
            )

            assert isinstance(analysis, NoveltyAnalysis)
            assert model_used == model_id


class TestPromptBuilding:
    """Test prompt construction."""

    def test_no_truncation_by_default(self, config):
        """Test that posts are NOT truncated when max_chars=0."""
        client = OpenRouterClient(config=config)

        long_post = "A" * 500
        context = [long_post]

        messages = client._build_messages(
            post_text="Target post",
            context_posts=context,
            channel_name="test",
        )

        user_content = messages[1]["content"]
        # Full text should be present (no truncation)
        assert "A" * 500 in user_content
        assert "..." not in user_content.split("1. ")[1].split("\n")[0]  # No ... after numbered post

    def test_truncation_when_configured(self, api_key):
        """Test that truncation works when explicitly configured."""
        config = NoveltyConfig(
            api_key=api_key,
            context_post_max_chars=100,  # Enable truncation
        )
        client = OpenRouterClient(config=config)

        long_post = "B" * 200  # Longer than max_chars
        context = [long_post]

        messages = client._build_messages(
            post_text="Target post",
            context_posts=context,
            channel_name="test",
        )

        user_content = messages[1]["content"]
        # Should be truncated
        assert "..." in user_content
        assert "B" * 200 not in user_content

    def test_context_limit(self, config):
        """Test that context posts are limited."""
        client = OpenRouterClient(config=config)

        # Create more posts than max_posts (10)
        context = [f"Post {i}" for i in range(20)]

        messages = client._build_messages(
            post_text="Target post",
            context_posts=context,
            channel_name="test",
        )

        user_content = messages[1]["content"]
        # Should only have first 10 posts
        assert "1. Post 0" in user_content
        assert "10. Post 9" in user_content
        assert "11. Post 10" not in user_content
