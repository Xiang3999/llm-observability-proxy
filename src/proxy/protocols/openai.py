"""OpenAI protocol stream parser."""

import json
import logging
from typing import Any

from .base import BaseStreamParser, ParsedResponse
from .registry import ProtocolRegistry

logger = logging.getLogger(__name__)


class OpenAIParser(BaseStreamParser):
    """Parser for OpenAI-style SSE streaming responses.

    OpenAI SSE format:
    data: {"id":"chatcmpl-xxx","choices":[{"delta":{"content":"Hello"},"finish_reason":null}]}
    data: {"id":"chatcmpl-xxx","choices":[{"delta":{},"finish_reason":"stop"}]}
    data: [DONE]
    """

    protocol_name = "openai"

    def parse_chunks(self, chunks: list[bytes]) -> ParsedResponse:
        """Parse OpenAI-style SSE chunks.

        Args:
            chunks: List of raw SSE chunk bytes

        Returns:
            ParsedResponse with content, usage, model, finish_reason, and metadata
        """
        if not chunks:
            return self._empty_response()

        try:
            raw = b"".join(chunks).decode("utf-8", errors="replace")
        except Exception:
            return self._empty_response()

        content_parts: list[str] = []
        reasoning_content_parts: list[str] = []
        reasoning_content_thinking_parts: list[str] = []
        tool_calls: list[dict] = []
        usage: dict[str, Any] = {}
        response_id: str | None = None
        model: str | None = None
        finish_reason = "stop"

        # Split by double newline to handle events spanning chunk boundaries
        for block in raw.split("\n\n"):
            block = block.strip()
            if not block:
                continue
            for line in block.split("\n"):
                line = line.strip()
                if line.startswith("data: "):
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        continue
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(obj, dict):
                        continue

                    response_id = response_id or obj.get("id")
                    model = model or obj.get("model")

                    choices = obj.get("choices") or []
                    if choices and isinstance(choices[0], dict):
                        delta = choices[0].get("delta") or {}
                        if isinstance(delta, dict):
                            # Content
                            if "content" in delta and delta["content"]:
                                content_parts.append(delta["content"])
                            # Reasoning content (DeepSeek / OpenAI reasoning models)
                            if "reasoning_content" in delta and delta["reasoning_content"]:
                                reasoning_content_parts.append(delta["reasoning_content"])
                            # Reasoning content thinking (some providers)
                            if "reasoning_content_thinking" in delta and delta["reasoning_content_thinking"]:
                                reasoning_content_thinking_parts.append(delta["reasoning_content_thinking"])
                            # Tool calls
                            if "tool_calls" in delta and delta["tool_calls"]:
                                for tc in delta["tool_calls"]:
                                    if isinstance(tc, dict):
                                        tool_calls.append(tc)
                            # Finish reason
                            if choices[0].get("finish_reason"):
                                finish_reason = choices[0]["finish_reason"]

                    # Top-level usage (OpenAI / DashScope)
                    if "usage" in obj and isinstance(obj["usage"], dict):
                        usage.update(self._parse_usage(obj["usage"]))
                    # DashScope/Kimi: usage at top level as input_tokens / output_tokens
                    if "prompt_tokens" in obj or "input_tokens" in obj or "output_tokens" in obj or "completion_tokens" in obj:
                        usage.update(self._parse_usage(obj))
                    # Nested usage.usage_details (Bailian/DashScope)
                    inner = (obj.get("usage") or {}) if isinstance(obj.get("usage"), dict) else {}
                    if inner.get("usage_details") or inner.get("input_tokens") is not None or inner.get("output_tokens") is not None:
                        usage.update(self._parse_usage(inner))

        content = "".join(content_parts) if content_parts else ""
        reasoning_content = "".join(reasoning_content_parts) if reasoning_content_parts else None
        reasoning_content_thinking = "".join(reasoning_content_thinking_parts) if reasoning_content_thinking_parts else None

        # Build metadata
        metadata: dict[str, Any] = {"id": response_id}
        if reasoning_content:
            metadata["reasoning_content"] = reasoning_content
        if reasoning_content_thinking:
            metadata["reasoning_content_thinking"] = reasoning_content_thinking
        if tool_calls:
            metadata["tool_calls"] = tool_calls

        # Final usage - already parsed with all fields preserved
        usage_final = usage if usage else self._default_usage()
        if not usage_final.get("prompt_tokens") and not usage_final.get("completion_tokens"):
            usage_final = self._default_usage()

        logger.debug(
            "openai_parser_reconstructed_usage",
            usage_final=usage_final,
        )

        return ParsedResponse(
            content=content,
            usage=usage_final,
            model=model,
            finish_reason=finish_reason,
            metadata=metadata,
        )

    def _empty_response(self) -> ParsedResponse:
        """Return empty response for error cases."""
        return ParsedResponse(
            content="",
            usage=self._default_usage(),
            model=None,
            finish_reason="stop",
            metadata={},
        )

    def _default_usage(self) -> dict[str, Any]:
        """Return default empty usage dict."""
        return {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}

    def _parse_usage(self, usage: dict[str, Any]) -> dict[str, Any]:
        """Parse usage dict preserving all fields.

        Extends normalize_usage to preserve additional fields like:
        - prompt_tokens_details
        - completion_tokens_details
        - cache_read_tokens
        - cache_read_input_tokens
        - cache_creation_input_tokens
        - usage_details

        Args:
            usage: Raw usage dict from provider

        Returns:
            Parsed usage dict with all fields preserved
        """
        result: dict[str, Any] = {}

        # Standard tokens fields
        prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
        completion_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
        total_tokens = usage.get("total_tokens")

        # Calculate total if not provided
        if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
            total_tokens = prompt_tokens + completion_tokens

        result["prompt_tokens"] = prompt_tokens
        result["completion_tokens"] = completion_tokens
        result["total_tokens"] = total_tokens

        # Preserve detailed fields
        for key in [
            "prompt_tokens_details",
            "completion_tokens_details",
            "cache_read_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "cache_write_tokens",
            "ephemeral_5m_input_tokens",
            "usage_details",
        ]:
            if key in usage:
                result[key] = usage[key]

        # Handle nested usage_details
        if "usage_details" in usage and isinstance(usage["usage_details"], dict):
            for key, value in usage["usage_details"].items():
                if key not in result:
                    result[key] = value

        # Handle prompt_tokens_details aliases for cache tokens
        prompt_details = usage.get("prompt_tokens_details")
        if isinstance(prompt_details, dict):
            if result.get("cache_read_tokens") is None:
                cached = prompt_details.get("cached_tokens")
                if cached is not None:
                    result["cache_read_tokens"] = cached
            if result.get("cache_read_input_tokens") is None:
                cached_input = prompt_details.get("cached_tokens")
                if cached_input is not None:
                    result["cache_read_input_tokens"] = cached_input

        # Handle completion_tokens_details for reasoning tokens
        comp_details = usage.get("completion_tokens_details")
        if isinstance(comp_details, dict):
            if result.get("reasoning_tokens") is None:
                reasoning = comp_details.get("reasoning_tokens")
                if reasoning is not None:
                    result["reasoning_tokens"] = reasoning

        return result


# Auto-register this parser at module load time
ProtocolRegistry().register("openai", OpenAIParser)
