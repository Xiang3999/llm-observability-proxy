"""Anthropic protocol stream parser."""

import json
import logging
from typing import Any

from .base import BaseStreamParser, ParsedResponse
from .registry import ProtocolRegistry

logger = logging.getLogger(__name__)


class AnthropicParser(BaseStreamParser):
    """Parser for Anthropic-style SSE streaming responses.

    Anthropic SSE format:
    event: message_start
    data: {"type":"message_start","message":{"id":"msg_xxx","model":"claude-3-5-sonnet-20241022","usage":{"input_tokens":10,"output_tokens":20}}}

    event: content_block_delta
    data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}

    event: message_delta
    data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":20}}
    """

    protocol_name = "anthropic"

    def parse_chunks(self, chunks: list[bytes]) -> ParsedResponse:
        """Parse Anthropic-style SSE chunks.

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
        usage: dict[str, Any] = {}
        response_id: str | None = None
        model: str | None = None
        stop_reason: str | None = None

        # Parse SSE format: event: and data: are on separate lines
        lines = raw.split("\n")
        current_event: str | None = None

        for line in lines:
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("event:"):
                current_event = line[6:].strip()
            elif line.startswith("data:"):
                payload = line[5:].strip()
                if payload == "[DONE]" or payload == "":
                    continue
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue

                response_id = response_id or obj.get("id") or obj.get("message", {}).get("id")
                model = model or obj.get("model") or obj.get("message", {}).get("model")

                # Use event type from event: line or data type from object
                event_type = obj.get("type", current_event or "")

                if event_type == "content_block_delta":
                    delta = obj.get("delta", {})
                    if delta.get("type") == "text_delta":
                        content_parts.append(delta.get("text", ""))
                    elif delta.get("type") == "thinking_delta":
                        reasoning_content_parts.append(delta.get("thinking", ""))
                elif event_type == "message_delta":
                    stop_reason = obj.get("delta", {}).get("stop_reason")
                    if "usage" in obj:
                        # message_delta has usage at top level with output_tokens
                        usage.update(obj["usage"])
                elif event_type == "message_start":
                    # message_start has usage nested in message.usage
                    msg_usage = obj.get("message", {}).get("usage", {})
                    if msg_usage:
                        usage.update(msg_usage)

                current_event = None  # Reset event after processing

        content = "".join(content_parts) if content_parts else ""
        reasoning_content = "".join(reasoning_content_parts) if reasoning_content_parts else None

        # Anthropic usage format - convert to standard format but preserve all fields
        prompt_tokens = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

        # Build usage dict with all fields
        usage_final: dict[str, Any] = {
            "prompt_tokens": prompt_tokens if prompt_tokens else None,
            "completion_tokens": completion_tokens if completion_tokens else None,
            "total_tokens": total_tokens if total_tokens else None,
        }

        # Preserve additional Anthropic/DashScope fields
        for key in ["cache_creation_input_tokens", "cache_read_input_tokens", "input_tokens", "output_tokens"]:
            if key in usage and key not in usage_final:
                usage_final[key] = usage[key]

        # Build metadata
        metadata: dict[str, Any] = {"id": response_id}
        if reasoning_content:
            metadata["reasoning_content"] = reasoning_content

        # Map Anthropic stop_reason to OpenAI finish_reason
        finish_reason = self._map_stop_reason(stop_reason)

        logger.debug(
            "anthropic_parser_reconstructed_usage",
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
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            model=None,
            finish_reason="stop",
            metadata={},
        )

    def _map_stop_reason(self, stop_reason: str | None) -> str:
        """Map Anthropic stop_reason to OpenAI finish_reason.

        Args:
            stop_reason: Anthropic stop reason

        Returns:
            OpenAI finish reason
        """
        if stop_reason is None:
            return "stop"

        mapping = {
            "end_turn": "stop",
            "max_tokens": "length",
            "stop_sequence": "stop",
            "tool_use": "tool_calls",
            "pause": "length",
        }
        return mapping.get(stop_reason, "stop")


# Auto-register this parser at module load time
ProtocolRegistry().register("anthropic", AnthropicParser)
