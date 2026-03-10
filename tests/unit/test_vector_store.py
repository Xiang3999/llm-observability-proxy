"""Unit tests for vector store."""

import pytest
import time
from src.cache.vector_store import InMemoryVectorStore, VectorEntry


class TestInMemoryVectorStore:
    """Tests for InMemoryVectorStore class."""

    @pytest.fixture
    def store(self):
        """Create a vector store for testing."""
        return InMemoryVectorStore(max_size=100)

    def test_insert_and_search(self, store):
        """Test inserting and searching vectors."""
        embedding = [0.1, 0.2, 0.3, 0.4, 0.5]

        store.insert(
            id="test-1",
            embedding=embedding,
            prompt_hash="abc123",
            response="Test response",
            model="gpt-4o-mini",
            ttl_seconds=3600
        )

        results = store.search(embedding, threshold=0.9)

        assert len(results) == 1
        entry, similarity = results[0]
        assert entry.id == "test-1"
        assert entry.response == "Test response"
        assert similarity >= 0.99  # Same vector should be very high similarity

    def test_search_below_threshold(self, store):
        """Test that vectors below threshold are not returned."""
        embedding1 = [1.0, 0.0, 0.0, 0.0, 0.0]
        embedding2 = [0.0, 1.0, 0.0, 0.0, 0.0]  # Orthogonal = 0 similarity

        store.insert(
            id="test-1",
            embedding=embedding1,
            prompt_hash="abc123",
            response="Response 1",
            model="gpt-4o-mini",
            ttl_seconds=3600
        )

        # Search with orthogonal vector
        results = store.search(embedding2, threshold=0.5)

        # Should return nothing (similarity is 0)
        assert len(results) == 0

    def test_search_returns_highest_similarity_first(self, store):
        """Test that results are sorted by similarity."""
        # Use non-normalized vectors to ensure different similarity scores
        embedding_query = [1.0, 0.0, 0.0, 0.0, 0.0]
        embedding_similar = [0.99, 0.01, 0.0, 0.0, 0.0]  # Very similar to query
        embedding_less_similar = [0.7, 0.7, 0.0, 0.0, 0.0]  # Less similar

        store.insert(
            id="test-1",
            embedding=embedding_less_similar,
            prompt_hash="hash2",
            response="Less similar",
            model="gpt-4o-mini",
            ttl_seconds=3600
        )

        store.insert(
            id="test-2",
            embedding=embedding_similar,
            prompt_hash="hash1",
            response="More similar",
            model="gpt-4o-mini",
            ttl_seconds=3600
        )

        # Use low threshold to get all results
        results = store.search(embedding_query, threshold=0.0)

        assert len(results) >= 1
        # If we get multiple results, first should be the more similar one
        if len(results) > 1:
            assert results[0][0].id == "test-2"
        else:
            # At minimum, the most similar should be returned first
            assert results[0][0].id == "test-2"

    def test_max_size_removes_oldest(self, store):
        """Test that oldest entry is removed when at max capacity."""
        small_store = InMemoryVectorStore(max_size=2)

        # Insert two entries
        small_store.insert(
            id="test-1",
            embedding=[0.1] * 5,
            prompt_hash="hash1",
            response="Response 1",
            model="gpt-4o-mini",
            ttl_seconds=3600
        )

        time.sleep(0.01)  # Small delay to ensure different timestamps

        small_store.insert(
            id="test-2",
            embedding=[0.2] * 5,
            prompt_hash="hash2",
            response="Response 2",
            model="gpt-4o-mini",
            ttl_seconds=3600
        )

        # Insert third entry - should remove oldest
        small_store.insert(
            id="test-3",
            embedding=[0.3] * 5,
            prompt_hash="hash3",
            response="Response 3",
            model="gpt-4o-mini",
            ttl_seconds=3600
        )

        # Should only have 2 entries
        assert len(small_store.entries) == 2
        # test-1 should be removed, test-2 and test-3 should remain
        assert "test-1" not in small_store.entries
        assert "test-2" in small_store.entries
        assert "test-3" in small_store.entries

    def test_cleanup_expired(self, store):
        """Test cleaning up expired entries."""
        # Insert with very short TTL
        store.insert(
            id="test-1",
            embedding=[0.1] * 5,
            prompt_hash="hash1",
            response="Response 1",
            model="gpt-4o-mini",
            ttl_seconds=0  # Already expired
        )

        store.insert(
            id="test-2",
            embedding=[0.2] * 5,
            prompt_hash="hash2",
            response="Response 2",
            model="gpt-4o-mini",
            ttl_seconds=3600  # Not expired
        )

        # Cleanup
        removed = store.cleanup_expired()

        assert removed == 1
        assert len(store.entries) == 1
        assert "test-2" in store.entries

    def test_stats(self, store):
        """Test getting store statistics."""
        store.insert(
            id="test-1",
            embedding=[0.1] * 5,
            prompt_hash="hash1",
            response="Response 1",
            model="gpt-4o-mini",
            ttl_seconds=0  # Expired
        )

        store.insert(
            id="test-2",
            embedding=[0.2] * 5,
            prompt_hash="hash2",
            response="Response 2",
            model="gpt-4o-mini",
            ttl_seconds=3600  # Not expired
        )

        stats = store.stats()

        assert stats["total_entries"] == 2
        assert stats["active_entries"] == 1
        assert stats["expired_entries"] == 1

    def test_remove(self, store):
        """Test removing an entry."""
        store.insert(
            id="test-1",
            embedding=[0.1] * 5,
            prompt_hash="hash1",
            response="Response 1",
            model="gpt-4o-mini",
            ttl_seconds=3600
        )

        result = store.remove("test-1")

        assert result is True
        assert len(store.entries) == 0

    def test_remove_nonexistent(self, store):
        """Test removing a nonexistent entry."""
        result = store.remove("nonexistent")

        assert result is False


class TestVectorEntry:
    """Tests for VectorEntry dataclass."""

    def test_is_expired_false(self):
        """Test that entry is not expired."""
        from datetime import datetime, timedelta

        entry = VectorEntry(
            id="test-1",
            embedding=[0.1, 0.2, 0.3],
            prompt_hash="abc123",
            response="Test",
            model="gpt-4o-mini",
            created_at=datetime.now(),
            ttl_seconds=3600
        )

        assert entry.is_expired() is False

    def test_is_expired_true(self):
        """Test that entry is expired."""
        from datetime import datetime, timedelta

        # Create entry that expired 1 hour ago
        entry = VectorEntry(
            id="test-1",
            embedding=[0.1, 0.2, 0.3],
            prompt_hash="abc123",
            response="Test",
            model="gpt-4o-mini",
            created_at=datetime.now() - timedelta(hours=2),
            ttl_seconds=3600  # 1 hour TTL
        )

        assert entry.is_expired() is True
