"""Tests for TextPreprocessor."""

import pytest

from storage.text_preprocessor import TextPreprocessor


class TestCleanForFts:
    def test_strips_html_entities(self):
        assert TextPreprocessor.clean_for_fts("hello &amp; world") == "hello & world"
        assert TextPreprocessor.clean_for_fts("a &lt;b&gt; c") == "a <b> c"

    def test_strips_urls(self):
        text = "Check https://example.com/path?q=1 here"
        assert TextPreprocessor.clean_for_fts(text) == "Check here"

    def test_strips_mentions(self):
        text = "Post by @durov about Telegram"
        assert TextPreprocessor.clean_for_fts(text) == "Post by about Telegram"

    def test_normalizes_whitespace(self):
        text = "  too   many    spaces  "
        assert TextPreprocessor.clean_for_fts(text) == "too many spaces"

    def test_none_returns_empty(self):
        assert TextPreprocessor.clean_for_fts(None) == ""

    def test_empty_returns_empty(self):
        assert TextPreprocessor.clean_for_fts("") == ""

    def test_combined(self):
        text = "Новость от @channel: смотри https://t.me/link &mdash; интересно"
        result = TextPreprocessor.clean_for_fts(text)
        assert "@channel" not in result
        assert "https://" not in result
        assert "\u2014" in result  # mdash decoded


class TestCleanForEmbedding:
    def test_keeps_mentions(self):
        text = "Post by @durov about Telegram"
        assert "@durov" in TextPreprocessor.clean_for_embedding(text)

    def test_keeps_hashtags(self):
        text = "News #crypto #bitcoin here"
        result = TextPreprocessor.clean_for_embedding(text)
        assert "#crypto" in result
        assert "#bitcoin" in result

    def test_strips_urls(self):
        text = "Check https://example.com here"
        assert "https://" not in TextPreprocessor.clean_for_embedding(text)

    def test_strips_html_entities(self):
        assert "&amp;" not in TextPreprocessor.clean_for_embedding("a &amp; b")

    def test_none_returns_empty(self):
        assert TextPreprocessor.clean_for_embedding(None) == ""


class TestHasCyrillic:
    def test_cyrillic_text(self):
        assert TextPreprocessor.has_cyrillic("Привет мир") is True

    def test_latin_text(self):
        assert TextPreprocessor.has_cyrillic("Hello world") is False

    def test_mixed_text(self):
        assert TextPreprocessor.has_cyrillic("Hello Привет") is True

    def test_none_returns_false(self):
        assert TextPreprocessor.has_cyrillic(None) is False

    def test_empty_returns_false(self):
        assert TextPreprocessor.has_cyrillic("") is False

    def test_ukrainian(self):
        assert TextPreprocessor.has_cyrillic("Привіт") is True
