"""Base classes for LLM protocol stream parsers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ParsedResponse:
    """Unified response format after parsing SSE chunks."""

    content: str
    usage: dict[str, Any]
    model: Optional[str]
    finish_reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseStreamParser(ABC):
    """Abstract base class for LLM streaming response parsers."""

    protocol_name: str = "base"

    @abstractmethod
    def parse_chunks(self, chunks: list[bytes]) -> ParsedResponse:
        """Parse raw SSE chunks into unified response format.

        Args:
            chunks: List of raw SSE chunk bytes

        Returns:
            ParsedResponse with content, usage, model, finish_reason, and metadata
        """
        pass

    def normalize_usage(self, usage: dict[str, Any]) -> dict[str, Any]:
        """Normalize usage fields to standard format.

        Handles different provider formats and computes total_tokens if missing.

        Args:
            usage: Raw usage dict from provider

        Returns:
            Normalized usage dict with prompt_tokens, completion_tokens, total_tokens
        """
        # Handle different field naming conventions
        prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
        completion_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
        total_tokens = usage.get("total_tokens")

        # Calculate total if not provided
        if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
            total_tokens = prompt_tokens + completion_tokens

        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

    def to_openai_format(self, response: ParsedResponse) -> dict[str, Any]:
        """Convert parsed response to OpenAI-compatible format.

        Args:
            response: ParsedResponse from parse_chunks()

        Returns:
            OpenAI-compatible response dict
        """
        # Build message with all captured fields
        message = {"role": "assistant", "content": response.content}

        # Add reasoning_content if present in metadata
        if response.metadata.get("reasoning_content"):
            message["reasoning_content"] = response.metadata["reasoning_content"]

        # Add reasoning_content_thinking if present in metadata
        if response.metadata.get("reasoning_content_thinking"):
            message["reasoning_content_thinking"] = response.metadata["reasoning_content_thinking"]

        # Add tool_calls if present in metadata
        if response.metadata.get("tool_calls"):
            message["tool_calls"] = response.metadata["tool_calls"]

        return {
            "id": response.metadata.get("id", ""),
            "object": "chat.completion",
            "model": response.model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": response.finish_reason,
                }
            ],
            "usage": response.usage,
        }
