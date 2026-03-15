"""Semantic Cache for LLM requests.

This module provides semantic caching functionality that:
1. Caches LLM responses based on semantic similarity of prompts
2. Returns cached responses for similar prompts to reduce API calls
3. Supports configurable similarity threshold and TTL

Usage:
    cache = SemanticCache(enabled=True, similarity_threshold=0.95)

    # Try to get cached response
    result = await cache.get(prompt="Hello", model="gpt-4o-mini")
    if result.hit:
        return result.response  # Cache hit!

    # Call LLM API and cache the response
    response = await call_llm_api(...)
    await cache.set(prompt="Hello", model="gpt-4o-mini", response=response)
"""

import asyncio
import hashlib
from collections import OrderedDict
from dataclasses import dataclass

from .embedding import get_embedding_generator
from .vector_store import InMemoryVectorStore


@dataclass
class CacheResult:
    """Result of a cache lookup."""

    hit: bool  # Whether cache was hit
    response: str | None = None  # Cached response (if hit)
    model: str | None = None  # Model used for cached response
    similarity: float = 0.0  # Similarity score (if hit)
    is_exact_match: bool = False  # Whether it was an exact prompt match


class SemanticCache:
    """Semantic cache for LLM responses."""

    def __init__(
        self,
        enabled: bool = False,
        similarity_threshold: float = 0.95,
        ttl_seconds: int = 3600,
        max_size: int = 10000,
        embedding_dimensions: int = 128
    ):
        """Initialize semantic cache.

        Args:
            enabled: Whether caching is enabled (default: False)
            similarity_threshold: Minimum similarity for cache hit (0.0 - 1.0)
            ttl_seconds: Time-to-live for cached entries in seconds
            max_size: Maximum number of cached entries
            embedding_dimensions: Dimension of embedding vectors
        """
        self.enabled = enabled
        self.similarity_threshold = similarity_threshold
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size

        self.vector_store = InMemoryVectorStore(max_size=max_size)
        self.embedding_generator = get_embedding_generator(embedding_dimensions)

        # Exact-match fast path: same prompt+model returns immediately (no embedding/vector)
        self._exact_cache: OrderedDict[str, tuple[str, str | None]] = OrderedDict()
        self._exact_max_size = min(10_000, max_size)

        # Stats
        self.hits = 0
        self.misses = 0
        self._exact_hits = 0

        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    def _hash_prompt(self, prompt: str) -> str:
        """Create a hash of the prompt for exact match detection."""
        return hashlib.sha256(prompt.encode()).hexdigest()

    def _extract_prompt(self, messages: list[dict]) -> str:
        """Extract the user prompt from messages array.

        For simplicity, we use the last user message.
        A more sophisticated approach could concatenate all messages.
        """
        if not messages:
            return ""

        # Find the last user message
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    # Handle array content (e.g., image + text)
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            return item.get("text", "")

        # Fallback: use the last message
        last_msg = messages[-1]
        if isinstance(last_msg, dict):
            content = last_msg.get("content", "")
            return content if isinstance(content, str) else str(content)

        return str(messages)

    async def get(
        self,
        messages: list[dict],
        model: str | None = None
    ) -> CacheResult:
        """Try to get a cached response.

        Args:
            messages: Chat messages array
            model: Model name (optional, for model-specific caching)

        Returns:
            CacheResult with hit/miss info and cached response if available
        """
        if not self.enabled:
            return CacheResult(hit=False)

        async with self._lock:
            prompt = self._extract_prompt(messages)
            if not prompt:
                return CacheResult(hit=False)

            prompt_hash = self._hash_prompt(prompt)
            exact_key = f"{prompt_hash}|{model or ''}"

            # Fast path: exact match (no embedding, no vector search)
            if exact_key in self._exact_cache:
                self._exact_hits += 1
                self.hits += 1
                response, cached_model = self._exact_cache[exact_key]
                self._exact_cache.move_to_end(exact_key)
                return CacheResult(
                    hit=True,
                    response=response,
                    model=cached_model,
                    similarity=1.0,
                    is_exact_match=True,
                )

            # Generate embedding and search
            embedding = self.embedding_generator.generate_for_prompt(prompt, model)
            results = self.vector_store.search(
                embedding=embedding,
                threshold=self.similarity_threshold,
                limit=1,
            )

            if not results:
                self.misses += 1
                return CacheResult(hit=False)

            entry, similarity = results[0]
            is_exact = entry.prompt_hash == prompt_hash
            self.hits += 1
            return CacheResult(
                hit=True,
                response=entry.response,
                model=entry.model,
                similarity=similarity,
                is_exact_match=is_exact,
            )

    async def set(
        self,
        messages: list[dict],
        response: str,
        model: str | None = None
    ) -> bool:
        """Cache a response.

        Args:
            messages: Chat messages array (request)
            response: LLM response to cache
            model: Model name (optional)

        Returns:
            True if cached successfully
        """
        if not self.enabled:
            return False

        async with self._lock:
            prompt = self._extract_prompt(messages)
            if not prompt:
                return False

            prompt_hash = self._hash_prompt(prompt)
            exact_key = f"{prompt_hash}|{model or ''}"

            while len(self._exact_cache) >= self._exact_max_size:
                self._exact_cache.popitem(last=False)
            self._exact_cache[exact_key] = (response, model)
            self._exact_cache.move_to_end(exact_key)

            embedding = self.embedding_generator.generate_for_prompt(prompt, model)
            entry_id = f"{prompt_hash}:{model or 'default'}"
            self.vector_store.insert(
                id=entry_id,
                embedding=embedding,
                prompt_hash=prompt_hash,
                response=response,
                model=model or "default",
                ttl_seconds=self.ttl_seconds,
            )
            return True

    def get_stats(self) -> dict:
        """Get cache statistics."""
        total = self.hits + self.misses
        hit_rate = self.hits / total if total > 0 else 0.0
        return {
            "enabled": self.enabled,
            "hits": self.hits,
            "misses": self.misses,
            "exact_hits": getattr(self, "_exact_hits", 0),
            "hit_rate": hit_rate,
            "similarity_threshold": self.similarity_threshold,
            "ttl_seconds": self.ttl_seconds,
            "vector_store": self.vector_store.stats(),
        }

    def clear(self) -> int:
        """Clear all cached entries. Returns count of cleared entries."""
        count = len(self.vector_store.entries)
        self.vector_store.entries.clear()
        self._exact_cache.clear()
        self.hits = 0
        self.misses = 0
        self._exact_hits = 0
        return count

    def cleanup(self) -> int:
        """Remove expired entries. Returns count of removed entries."""
        return self.vector_store.cleanup_expired()
