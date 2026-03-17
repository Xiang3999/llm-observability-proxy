"""Anthropic API protocol converter.

Converts between OpenAI and Anthropic API formats bidirectionally.

Anthropic Messages API format:
- POST /v1/messages
- Request: {model, max_tokens, messages, system, tools, ...}
- Response: {id, type, role, content, model, stop_reason, usage}
- Stream: SSE with events (message_start, content_block_delta, message_delta, etc.)

OpenAI Chat Completions format:
- POST /v1/chat/completions
- Request: {model, messages, tools, stream, ...}
- Response: {id, object, choices: [{message, finish_reason}], usage}
- Stream: SSE with data: {"choices": [{"delta": {...}}]}
"""

import hashlib
import json
from typing import Any, Optional, List, Dict, Union, Tuple


def _extract_system_from_messages(messages: List[Dict]) -> Tuple[Optional[Union[str, List[Dict]]], List[Dict]]:
    """Extract system prompt from OpenAI-style messages.

    OpenAI format: messages can have role="system"
    Anthropic format: system is a separate top-level field

    Returns:
        (system_content, remaining_messages)
    """
    system_content = None
    remaining_messages = []

    for msg in messages:
        if msg.get("role") == "system":
            # Anthropic supports both string and content block array for system
            system_content = msg.get("content")
        else:
            remaining_messages.append(msg)

    return system_content, remaining_messages


def _convert_openai_tool_to_anthropic(tool: dict) -> dict:
    """Convert OpenAI tool format to Anthropic format.

    OpenAI:
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather",
            "parameters": {"type": "object", "properties": {...}}
        }
    }

    Anthropic:
    {
        "name": "get_weather",
        "description": "Get weather",
        "input_schema": {"type": "object", "properties": {...}}
    }
    """
    function = tool.get("function", {})
    return {
        "name": function.get("name", ""),
        "description": function.get("description", ""),
        "input_schema": function.get("parameters", {"type": "object"})
    }


def convert_anthropic_tool_to_openai(tool: dict) -> dict:
    """Convert Anthropic tool format to OpenAI format.

    Anthropic:
    {
        "name": "get_weather",
        "description": "Get weather",
        "input_schema": {"type": "object", "properties": {...}}
    }

    OpenAI:
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather",
            "parameters": {"type": "object", "properties": {...}}
        }
    }
    """
    return {
        "type": "function",
        "function": {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object"})
        }
    }


def convert_openai_to_anthropic(body: dict) -> dict:
    """Convert OpenAI chat completions request to Anthropic messages request.

    Args:
        body: OpenAI format request body

    Returns:
        Anthropic format request body
    """
    messages = body.get("messages", [])
    system, remaining_messages = _extract_system_from_messages(messages)

    # Build Anthropic request
    anthropic_body = {
        "model": body.get("model", "claude-3-5-sonnet-20241022"),
        "max_tokens": body.get("max_tokens", 1024),
        "messages": remaining_messages,
    }

    # Add system if present
    if system is not None:
        anthropic_body["system"] = system

    # Add optional parameters
    if "temperature" in body:
        anthropic_body["temperature"] = body["temperature"]
    if "top_p" in body:
        anthropic_body["top_p"] = body["top_p"]
    if "stop" in body:
        anthropic_body["stop_sequences"] = body["stop"] if isinstance(body["stop"], list) else [body["stop"]]
    if "stream" in body:
        anthropic_body["stream"] = body["stream"]

    # Convert tools
    if "tools" in body:
        anthropic_body["tools"] = [
            _convert_openai_tool_to_anthropic(t) for t in body["tools"]
        ]

    # Tool choice
    if "tool_choice" in body:
        tc = body["tool_choice"]
        if tc == "auto":
            anthropic_body["tool_choice"] = {"type": "auto"}
        elif tc == "required":
            anthropic_body["tool_choice"] = {"type": "any"}
        elif tc == "none":
            anthropic_body["tool_choice"] = {"type": "none"}
        elif isinstance(tc, dict) and tc.get("type") == "function":
            anthropic_body["tool_choice"] = {
                "type": "tool",
                "name": tc.get("function", {}).get("name")
            }

    # Metadata for tracking
    if "metadata" in body:
        anthropic_body["metadata"] = body["metadata"]

    return anthropic_body


def _extract_text_from_content(content: Any) -> str:
    """Extract text from Anthropic content format."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
                elif item.get("type") == "tool_use":
                    # Include tool_use as formatted text
                    texts.append(f"[Tool: {item.get('name', '')}]")
        return "".join(texts)
    return str(content)


def _extract_reasoning_from_content(content: Any) -> Optional[str]:
    """Extract reasoning/thinking from Anthropic content format."""
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "thinking":
                return item.get("thinking", "")
    return None


def _convert_anthropic_tool_use_to_openai(content_block: dict) -> dict:
    """Convert Anthropic tool_use content block to OpenAI tool_calls format."""
    return {
        "id": content_block.get("id", ""),
        "type": "function",
        "function": {
            "name": content_block.get("name", ""),
            "arguments": json.dumps(content_block.get("input", {}))
        }
    }


def convert_anthropic_to_openai(response: dict, request_model: Optional[str] = None) -> dict:
    """Convert Anthropic response to OpenAI chat completions format.

    Args:
        response: Anthropic format response body
        request_model: Original model from request (for logging)

    Returns:
        OpenAI format response body
    """
    # Handle both "message" type (non-stream) and consolidated stream responses
    response_type = response.get("type", "message")

    if response_type == "message" or "content" in response:
        # Non-stream or fully consolidated stream response
        content = response.get("content", [])
        content_text = _extract_text_from_content(content)
        reasoning_content = _extract_reasoning_from_content(content)

        # Extract tool calls
        tool_calls = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "tool_use":
                        tool_calls.append(_convert_anthropic_tool_use_to_openai(item))
                    elif item.get("type") == "server_tool_use":
                        tool_calls.append({
                            "id": item.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": item.get("name", ""),
                                "arguments": json.dumps(item.get("input", {}))
                            }
                        })

        # Build message
        message = {
            "role": "assistant",
            "content": content_text,
        }
        if reasoning_content:
            message["reasoning_content"] = reasoning_content
        if tool_calls:
            message["tool_calls"] = tool_calls

        # Extract usage
        usage = response.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)

        return {
            "id": response.get("id", ""),
            "object": "chat.completion",
            "model": response.get("model", request_model or ""),
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": _map_stop_reason(response.get("stop_reason")),
                "logprobs": None
            }],
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            }
        }

    # Fallback for unknown formats
    return {
        "id": response.get("id", ""),
        "object": "chat.completion",
        "model": response.get("model", request_model or ""),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": str(response)},
            "finish_reason": "stop"
        }],
        "usage": {}
    }


def _map_stop_reason(stop_reason: Optional[str]) -> str:
    """Map Anthropic stop_reason to OpenAI finish_reason."""
    if stop_reason is None:
        return "stop"

    mapping = {
        "end_turn": "stop",
        "max_tokens": "length",
        "stop_sequence": "stop",
        "tool_use": "tool_calls",
        "pause": "length",  # For continued conversations
    }
    return mapping.get(stop_reason, "stop")


def get_prompt_hash(content: str) -> str:
    """Generate short hash for prompt identification."""
    return hashlib.md5(content.encode()).hexdigest()[:12]


def extract_system_prompts_from_anthropic(body: dict) -> Optional[str]:
    """Extract system prompt from Anthropic request body."""
    system = body.get("system")
    if system is None:
        return None
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        # Content block array format
        texts = []
        for item in system:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "".join(texts) if texts else None
    return None
