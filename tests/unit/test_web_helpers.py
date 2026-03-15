"""Unit tests for web helper functions."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from src.web.routes import (
    calculate_daily_distribution,
    extract_cron_task_info,
    extract_system_prompts,
    get_cache_read_info,
    get_prompt_hash,
)


class TestPromptHash:
    """Tests for prompt hashing."""

    def test_get_prompt_hash_format(self):
        """Test that prompt hashes have correct format (12 chars)."""
        content = "You are a helpful assistant."
        hash_result = get_prompt_hash(content)
        assert len(hash_result) == 12
        assert all(c in "0123456789abcdef" for c in hash_result)

    def test_get_prompt_hash_consistency(self):
        """Test that same content produces same hash."""
        content = "You are a helpful assistant."
        hash1 = get_prompt_hash(content)
        hash2 = get_prompt_hash(content)
        assert hash1 == hash2

    def test_get_prompt_hash_uniqueness(self):
        """Test that different content produces different hashes."""
        content1 = "You are a helpful assistant."
        content2 = "You are a malicious assistant."
        assert get_prompt_hash(content1) != get_prompt_hash(content2)


class TestCronTaskExtraction:
    """Tests for cron task info extraction."""

    def test_extract_cron_task_info_success(self):
        """Test extracting cron task info from valid request."""
        request_body = {
            "messages": [
                {"role": "user", "content": "[cron:abc-123 Daily Backup] Running backup"}
            ]
        }
        task_id = extract_cron_task_info(request_body)
        assert task_id == "abc-123"

    def test_extract_cron_task_info_no_cron(self):
        """Test extraction when no cron task present."""
        request_body = {
            "messages": [
                {"role": "user", "content": "Regular user message"}
            ]
        }
        task_id = extract_cron_task_info(request_body)
        assert task_id is None

    def test_extract_cron_task_info_empty_body(self):
        """Test extraction with empty request body."""
        assert extract_cron_task_info(None) is None
        assert extract_cron_task_info({}) is None

    def test_extract_cron_task_info_multiple_messages(self):
        """Test extraction with multiple messages."""
        request_body = {
            "messages": [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "[cron:abc-123-def Task Name] Do something"},
                {"role": "assistant", "content": "OK"}
            ]
        }
        task_id = extract_cron_task_info(request_body)
        assert task_id == "abc-123-def"


class TestCacheReadInfo:
    """Tests for cache read info display."""

    def test_get_cache_read_info_with_tokens(self):
        """Test display when cache tokens present."""
        req = MagicMock()
        req.cache_read_tokens = 1500
        result = get_cache_read_info(req)
        assert result == "1,500"

    def test_get_cache_read_info_zero_tokens(self):
        """Test display when zero cache tokens."""
        req = MagicMock()
        req.cache_read_tokens = 0
        result = get_cache_read_info(req)
        assert result == "-"

    def test_get_cache_read_info_none_tokens(self):
        """Test display when cache tokens is None."""
        req = MagicMock()
        req.cache_read_tokens = None
        result = get_cache_read_info(req)
        assert result == "-"


class TestSystemPromptExtraction:
    """Tests for system prompt extraction."""

    def test_extract_system_prompts_basic(self):
        """Test basic system prompt extraction."""
        req1 = MagicMock()
        req1.request_body = {
            "messages": [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"}
            ]
        }
        req1.created_at = datetime.now()
        req1.model = "gpt-4"
        req1.id = 1

        result = extract_system_prompts([req1])

        assert len(result) == 1
        prompt_hash = get_prompt_hash("You are helpful")
        assert prompt_hash in result
        assert result[prompt_hash]["count"] == 1
        assert result[prompt_hash]["content"] == "You are helpful"

    def test_extract_system_prompts_aggregation(self):
        """Test that multiple requests with same prompt are aggregated."""
        prompt_content = "You are helpful"
        req1 = MagicMock()
        req1.request_body = {
            "messages": [
                {"role": "system", "content": prompt_content},
                {"role": "user", "content": "Hello"}
            ]
        }
        req1.created_at = datetime.now()
        req1.model = "gpt-4"

        req2 = MagicMock()
        req2.request_body = {
            "messages": [
                {"role": "system", "content": prompt_content},
                {"role": "user", "content": "Hi there"}
            ]
        }
        req2.created_at = datetime.now() + timedelta(hours=1)
        req2.model = "gpt-3.5"

        result = extract_system_prompts([req1, req2])

        prompt_hash = get_prompt_hash(prompt_content)
        assert result[prompt_hash]["count"] == 2
        assert "gpt-4" in result[prompt_hash]["model_counts"]
        assert "gpt-3.5" in result[prompt_hash]["model_counts"]

    def test_extract_system_prompts_no_system_message(self):
        """Test extraction when no system message present."""
        req = MagicMock()
        req.request_body = {
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi!"}
            ]
        }
        req.created_at = datetime.now()
        req.model = "gpt-4"

        result = extract_system_prompts([req])
        assert len(result) == 0

    def test_extract_system_prompts_array_content(self):
        """Test extraction with array-format system content."""
        req = MagicMock()
        req.request_body = {
            "messages": [
                {
                    "role": "system",
                    "content": [
                        {"type": "text", "text": "You are"},
                        {"type": "text", "text": "helpful"}
                    ]
                },
                {"role": "user", "content": "Hello"}
            ]
        }
        req.created_at = datetime.now()
        req.model = "gpt-4"

        result = extract_system_prompts([req])

        assert len(result) == 1
        # Content should be joined
        prompt_data = list(result.values())[0]
        assert "You are" in prompt_data["content"]
        assert "helpful" in prompt_data["content"]


class TestDailyDistribution:
    """Tests for daily distribution calculation."""

    def test_calculate_daily_distribution_basic(self):
        """Test basic daily distribution calculation."""
        base_date = datetime(2024, 1, 15, 10, 30, 0)
        req1 = MagicMock()
        req1.created_at = base_date
        req2 = MagicMock()
        req2.created_at = base_date + timedelta(hours=5)
        req3 = MagicMock()
        req3.created_at = base_date + timedelta(days=1)

        result = calculate_daily_distribution([req1, req2, req3])

        assert result["2024-01-15"] == 2
        assert result["2024-01-16"] == 1

    def test_calculate_daily_distribution_empty(self):
        """Test with empty request list."""
        result = calculate_daily_distribution([])
        assert result == {}

    def test_calculate_daily_distribution_single_day(self):
        """Test when all requests are on same day."""
        base_date = datetime(2024, 1, 15)
        requests = []
        for i in range(5):
            req = MagicMock()
            req.created_at = base_date + timedelta(hours=i)
            requests.append(req)

        result = calculate_daily_distribution(requests)
        assert len(result) == 1
        assert result["2024-01-15"] == 5
