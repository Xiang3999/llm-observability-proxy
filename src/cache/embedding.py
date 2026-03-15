"""Embedding generator for semantic cache.

This module provides a simple embedding generator using hash-based pseudo-embeddings.
For production use, replace with a real embedding model like:
- OpenAI embeddings (text-embedding-3-small)
- Sentence Transformers (all-MiniLM-L6-v2)
- Cohere embeddings
- Jina embeddings
"""

import hashlib
import math


class HashEmbeddingGenerator:
    """Simple hash-based pseudo-embedding generator.

    This is a placeholder for demonstration purposes.
    It produces deterministic vectors based on input text hash,
    but does NOT capture semantic meaning.

    For production, use a real embedding model.
    """

    def __init__(self, dimensions: int = 128):
        self.dimensions = dimensions

    def generate(self, text: str) -> list[float]:
        """Generate embedding vector for text.

        Args:
            text: Input text to embed

        Returns:
            List of floats (embedding vector)
        """
        # Use hash to generate deterministic pseudo-embedding
        hash_bytes = hashlib.sha256(text.encode()).digest()

        # Convert hash bytes to floats
        embedding = []
        for i in range(self.dimensions):
            byte_idx = i % len(hash_bytes)
            # Map byte value (0-255) to float (-1 to 1)
            value = (hash_bytes[byte_idx] / 255.0) * 2 - 1
            embedding.append(value)

        return embedding

    def generate_for_prompt(self, prompt: str, model: str | None = None) -> list[float]:
        """Generate embedding for a chat prompt.

        Args:
            prompt: The user prompt
            model: Optional model name to include in embedding

        Returns:
            Embedding vector
        """
        # Include model in embedding key for model-specific caching
        text = f"{model}:{prompt}" if model else prompt
        return self.generate(text)


class DummyEmbeddingGenerator:
    """Dummy embedding generator that returns constant vectors.

    Used for testing without actual embedding computation.
    """

    def __init__(self, dimensions: int = 128):
        self.dimensions = dimensions

    def generate(self, text: str) -> list[float]:
        """Generate a deterministic but simple embedding."""
        # Use text length as seed for deterministic output
        seed = len(text) % 100

        embedding = []
        for i in range(self.dimensions):
            # Simple deterministic pattern based on position and seed
            value = math.sin(seed + i * 0.1)
            embedding.append(value)

        return embedding

    def generate_for_prompt(self, prompt: str, model: str | None = None) -> list[float]:
        """Generate embedding for a chat prompt."""
        text = f"{model}:{prompt}" if model else prompt
        return self.generate(text)


# Default generator
_default_generator: HashEmbeddingGenerator | None = None


def get_embedding_generator(dimensions: int = 128) -> HashEmbeddingGenerator:
    """Get or create the default embedding generator."""
    global _default_generator
    if _default_generator is None or _default_generator.dimensions != dimensions:
        _default_generator = HashEmbeddingGenerator(dimensions)
    return _default_generator
