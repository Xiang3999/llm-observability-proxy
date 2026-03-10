"""Unit tests for API key management."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.auth.key_manager import (
    generate_proxy_key,
    hash_key,
    verify_key,
    KeyManager
)
from src.models.provider_key import ProviderType


class TestProxyKeyGeneration:
    """Tests for proxy key generation."""

    def test_generate_proxy_key_format(self):
        """Test that generated keys have the correct format."""
        key = generate_proxy_key()

        # Check format: sk-helicone-proxy-<random>-<uuid>
        assert key.startswith("sk-helicone-proxy-")
        parts = key.split("-")
        assert len(parts) >= 5  # sk, helicone, proxy, random, uuid (with dashes)

    def test_generate_proxy_key_uniqueness(self):
        """Test that generated keys are unique."""
        keys = [generate_proxy_key() for _ in range(100)]
        assert len(keys) == len(set(keys))


class TestKeyHashing:
    """Tests for key hashing."""

    def test_hash_key(self):
        """Test key hashing."""
        key = "test-key-123"
        hashed = hash_key(key)

        # Hash should be different from original
        assert hashed != key
        # Hash should start with algorithm identifier
        assert hashed.startswith("$")

    def test_verify_key_success(self):
        """Test successful key verification."""
        key = "test-key-123"
        hashed = hash_key(key)

        assert verify_key(key, hashed) is True

    def test_verify_key_failure(self):
        """Test failed key verification."""
        key = "test-key-123"
        wrong_key = "wrong-key"
        hashed = hash_key(key)

        assert verify_key(wrong_key, hashed) is False


class TestKeyManager:
    """Tests for KeyManager class."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_create_provider_key(self, mock_db):
        """Test creating a provider key."""
        manager = KeyManager(mock_db)

        result = await manager.create_provider_key(
            name="Test Key",
            provider=ProviderType.OPENAI,
            api_key="sk-test123"
        )

        # Verify the key was "added" to db
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_proxy_key(self, mock_db):
        """Test proxy key validation."""
        manager = KeyManager(mock_db)

        # Mock the database response
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MagicMock()
        mock_db.execute.return_value = mock_result

        result = await manager.validate_proxy_key("sk-helicone-proxy-test")

        # Should call execute
        mock_db.execute.assert_called_once()


class TestProviderType:
    """Tests for ProviderType enum."""

    def test_provider_types(self):
        """Test that all expected provider types exist."""
        assert ProviderType.OPENAI.value == "openai"
        assert ProviderType.ANTHROPIC.value == "anthropic"
        assert ProviderType.GEMINI.value == "gemini"
        assert ProviderType.AZURE_OPENAI.value == "azure_openai"
        assert ProviderType.CUSTOM.value == "custom"
