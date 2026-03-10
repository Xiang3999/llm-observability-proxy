"""In-memory vector store for semantic cache.

This module provides a simple in-memory vector store for semantic similarity search.
For production use, consider using a dedicated vector database like:
- FAISS (Facebook AI Similarity Search)
- ChromaDB
- Qdrant
- Pinecone
- Weaviate
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import hashlib


@dataclass
class VectorEntry:
    """A vector entry with embedding and cached response."""

    id: str
    embedding: list[float]
    prompt_hash: str  # For exact match detection
    response: str
    model: str
    created_at: datetime
    ttl_seconds: int
    hit_count: int = 0

    def is_expired(self) -> bool:
        """Check if this entry has expired."""
        now = datetime.now()
        age = (now - self.created_at).total_seconds()
        return age > self.ttl_seconds


class InMemoryVectorStore:
    """Simple in-memory vector store with cosine similarity search."""

    def __init__(self, max_size: int = 10000):
        self.max_size = max_size
        self.entries: dict[str, VectorEntry] = {}

    def _normalize(self, vector: list[float]) -> list[float]:
        """Normalize a vector to unit length."""
        magnitude = math.sqrt(sum(x * x for x in vector))
        if magnitude == 0:
            return vector
        return [x / magnitude for x in vector]

    def _cosine_similarity(self, v1: list[float], v2: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        # Normalize vectors
        v1_norm = self._normalize(v1)
        v2_norm = self._normalize(v2)

        # Dot product of normalized vectors = cosine similarity
        similarity = sum(a * b for a, b in zip(v1_norm, v2_norm))
        return max(-1.0, min(1.0, similarity))  # Clamp to [-1, 1]

    def search(
        self,
        embedding: list[float],
        threshold: float = 0.95,
        limit: int = 1
    ) -> list[tuple[VectorEntry, float]]:
        """Search for similar vectors above threshold.

        Args:
            embedding: Query embedding vector
            threshold: Minimum similarity threshold (0.0 - 1.0)
            limit: Maximum number of results to return

        Returns:
            List of (entry, similarity_score) tuples
        """
        results = []

        for entry in self.entries.values():
            # Skip expired entries
            if entry.is_expired():
                continue

            similarity = self._cosine_similarity(embedding, entry.embedding)

            if similarity >= threshold:
                results.append((entry, similarity))

        # Sort by similarity (descending)
        results.sort(key=lambda x: x[1], reverse=True)

        return results[:limit]

    def insert(
        self,
        id: str,
        embedding: list[float],
        prompt_hash: str,
        response: str,
        model: str,
        ttl_seconds: int
    ) -> VectorEntry:
        """Insert a new vector entry.

        If the store is at max capacity, removes the oldest entry.
        """
        # Check for exact duplicate
        for existing in self.entries.values():
            if existing.prompt_hash == prompt_hash and not existing.is_expired():
                # Update existing entry
                existing.hit_count += 1
                return existing

        # Remove oldest if at capacity
        if len(self.entries) >= self.max_size:
            oldest_id = min(
                self.entries.keys(),
                key=lambda k: self.entries[k].created_at
            )
            del self.entries[oldest_id]

        entry = VectorEntry(
            id=id,
            embedding=embedding,
            prompt_hash=prompt_hash,
            response=response,
            model=model,
            created_at=datetime.now(),
            ttl_seconds=ttl_seconds,
            hit_count=1
        )
        self.entries[id] = entry
        return entry

    def remove(self, id: str) -> bool:
        """Remove an entry by ID."""
        if id in self.entries:
            del self.entries[id]
            return True
        return False

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count of removed entries."""
        expired = [k for k, v in self.entries.items() if v.is_expired()]
        for k in expired:
            del self.entries[k]
        return len(expired)

    def stats(self) -> dict:
        """Get store statistics."""
        now = datetime.now()
        active = sum(1 for v in self.entries.values() if not v.is_expired())
        expired = len(self.entries) - active
        total_hits = sum(v.hit_count for v in self.entries.values())

        return {
            "total_entries": len(self.entries),
            "active_entries": active,
            "expired_entries": expired,
            "total_hits": total_hits,
            "hit_rate": total_hits / (total_hits + len(self.entries)) if total_hits > 0 else 0
        }
