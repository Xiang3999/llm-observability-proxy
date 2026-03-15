"""Unit tests for semantic cache."""


import pytest

from src.cache.semantic_cache import CacheResult, SemanticCache


class TestSemanticCache:
    """Tests for SemanticCache class."""

    @pytest.fixture
    def cache_disabled(self):
        """Create a disabled cache."""
        return SemanticCache(enabled=False)

    @pytest.fixture
    def cache_enabled(self):
        """Create an enabled cache with low threshold for testing."""
        return SemanticCache(
            enabled=True,
            similarity_threshold=0.7,  # Lower threshold for testing
            ttl_seconds=3600,
            max_size=100
        )

    @pytest.mark.asyncio
    async def test_cache_disabled_returns_miss(self, cache_disabled):
        """Test that disabled cache always returns miss."""
        result = await cache_disabled.get(
            messages=[{"role": "user", "content": "Hello"}],
            model="gpt-4o-mini"
        )

        assert result.hit is False
        assert result.response is None

    @pytest.mark.asyncio
    async def test_cache_miss_on_first_request(self, cache_enabled):
        """Test that first request is a cache miss."""
        result = await cache_enabled.get(
            messages=[{"role": "user", "content": "Hello"}],
            model="gpt-4o-mini"
        )

        assert result.hit is False

    @pytest.mark.asyncio
    async def test_cache_hit_after_set(self, cache_enabled):
        """Test that cached response is returned on similar request."""
        messages = [{"role": "user", "content": "Test prompt for cache"}]
        response = "This is a test response"

        # First request - miss
        miss_result = await cache_enabled.get(messages, model="gpt-4o-mini")
        assert miss_result.hit is False

        # Cache the response
        await cache_enabled.set(messages, response, model="gpt-4o-mini")

        # Second request - hit
        hit_result = await cache_enabled.get(messages, model="gpt-4o-mini")
        assert hit_result.hit is True
        assert hit_result.response == response
        assert hit_result.is_exact_match is True

    @pytest.mark.asyncio
    async def test_cache_stats(self, cache_enabled):
        """Test cache statistics."""
        messages = [{"role": "user", "content": "Test prompt"}]

        # Generate some hits and misses
        await cache_enabled.get(messages)  # Miss
        await cache_enabled.set(messages, "Response")
        await cache_enabled.get(messages)  # Hit
        await cache_enabled.get([{"role": "user", "content": "Different"}])  # Miss

        stats = cache_enabled.get_stats()

        assert stats["enabled"] is True
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert stats["hit_rate"] == 1 / 3

    @pytest.mark.asyncio
    async def test_cache_clear(self, cache_enabled):
        """Test clearing the cache."""
        messages = [{"role": "user", "content": "Test prompt"}]

        # Add some entries
        await cache_enabled.set(messages, "Response 1")
        await cache_enabled.set([{"role": "user", "content": "Another"}], "Response 2")

        # Clear
        cleared = cache_enabled.clear()

        assert cleared == 2
        stats = cache_enabled.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    @pytest.mark.asyncio
    async def test_extract_prompt_from_messages(self, cache_enabled):
        """Test prompt extraction from chat messages."""
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello there"},
            {"role": "assistant", "content": "Hi!"}
        ]

        prompt = cache_enabled._extract_prompt(messages)
        assert prompt == "Hello there"

    @pytest.mark.asyncio
    async def test_extract_prompt_last_user_message(self, cache_enabled):
        """Test that last user message is extracted."""
        messages = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Second question"}
        ]

        prompt = cache_enabled._extract_prompt(messages)
        assert prompt == "Second question"

    @pytest.mark.asyncio
    async def test_hash_prompt_deterministic(self, cache_enabled):
        """Test that prompt hashing is deterministic."""
        prompt = "Test prompt for hashing"

        hash1 = cache_enabled._hash_prompt(prompt)
        hash2 = cache_enabled._hash_prompt(prompt)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length

    @pytest.mark.asyncio
    async def test_cache_with_empty_messages(self, cache_enabled):
        """Test cache with empty messages."""
        result = await cache_enabled.get(messages=[], model="gpt-4o-mini")

        assert result.hit is False

    @pytest.mark.asyncio
    async def test_cache_set_with_empty_messages(self, cache_enabled):
        """Test setting cache with empty messages."""
        result = await cache_enabled.set(
            messages=[],
            response="Some response",
            model="gpt-4o-mini"
        )

        assert result is False


class TestCacheResult:
    """Tests for CacheResult dataclass."""

    def test_cache_result_default_values(self):
        """Test CacheResult default values."""
        result = CacheResult(hit=False)

        assert result.hit is False
        assert result.response is None
        assert result.model is None
        assert result.similarity == 0.0
        assert result.is_exact_match is False

    def test_cache_result_with_values(self):
        """Test CacheResult with explicit values."""
        result = CacheResult(
            hit=True,
            response="Cached response",
            model="gpt-4o-mini",
            similarity=0.98,
            is_exact_match=True
        )

        assert result.hit is True
        assert result.response == "Cached response"
        assert result.model == "gpt-4o-mini"
        assert result.similarity == 0.98
        assert result.is_exact_match is True
