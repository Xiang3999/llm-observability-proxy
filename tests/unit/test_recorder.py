"""Unit tests for request recorder."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.recorder.recorder import RequestRecorder


class TestRequestRecorder:
    """Tests for RequestRecorder class."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_record_request_start(self, mock_db):
        """Test recording request start."""
        recorder = RequestRecorder(mock_db)

        start_time = datetime.now()
        result = await recorder.record_request_start(
            proxy_key_id="test-proxy-key-id",
            path="/v1/chat/completions",
            method="POST",
            model="gpt-4o-mini",
            provider="openai",
            body={"messages": [{"role": "user", "content": "Hello"}]},
            start_time=start_time
        )

        # Verify database interaction
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()
        mock_db.refresh.assert_called_once()

        # Verify recorded data
        assert result.proxy_key_id == "test-proxy-key-id"
        assert result.request_path == "/v1/chat/completions"
        assert result.model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_record_response(self, mock_db):
        """Test recording response."""
        recorder = RequestRecorder(mock_db)

        # First record request start
        start_time = datetime.now()
        await recorder.record_request_start(
            proxy_key_id="test-key",
            path="/v1/chat/completions",
            method="POST",
            model="gpt-4o-mini",
            provider="openai",
            body={},
            start_time=start_time
        )

        # Then record response
        end_time = datetime.now()
        await recorder.record_response(
            status_code=200,
            headers={"content-type": "application/json"},
            body={
                "choices": [{"message": {"role": "assistant", "content": "Hi!"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
            },
            end_time=end_time
        )

        # Verify response was recorded
        assert recorder.current_request is not None
        assert recorder.current_request.status_code == 200
        assert recorder.current_request.prompt_tokens == 10
        assert recorder.current_request.completion_tokens == 5
        assert recorder.current_request.total_tokens == 15

    @pytest.mark.asyncio
    async def test_record_error(self, mock_db):
        """Test recording error."""
        recorder = RequestRecorder(mock_db)

        # First record request start
        await recorder.record_request_start(
            proxy_key_id="test-key",
            path="/v1/chat/completions",
            method="POST",
            model="gpt-4o-mini",
            provider="openai",
            body={},
            start_time=datetime.now()
        )

        # Record error
        await recorder.record_error(
            status_code=504,
            error_message="Request timeout"
        )

        # Verify error was recorded
        assert recorder.current_request.status_code == 504
        assert recorder.current_request.error_message == "Request timeout"

    @pytest.mark.asyncio
    async def test_finalize(self, mock_db):
        """Test finalizing recording."""
        recorder = RequestRecorder(mock_db)

        # Record a request
        await recorder.record_request_start(
            proxy_key_id="test-key",
            path="/v1/chat/completions",
            method="POST",
            model="gpt-4o-mini",
            provider="openai",
            body={},
            start_time=datetime.now()
        )

        # Finalize
        result = await recorder.finalize()

        # Should return the request and clear current
        assert result is not None
        assert recorder.current_request is None

    @pytest.mark.asyncio
    async def test_record_request_extract_user(self, mock_db):
        """Test that user_id is extracted from request body."""
        recorder = RequestRecorder(mock_db)

        await recorder.record_request_start(
            proxy_key_id="test-key",
            path="/v1/chat/completions",
            method="POST",
            model="gpt-4o-mini",
            provider="openai",
            body={"user": "user-123", "messages": []},
            start_time=datetime.now()
        )

        # Verify user_id was extracted
        assert recorder.current_request.user_id == "user-123"
