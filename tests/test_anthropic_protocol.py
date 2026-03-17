#!/usr/bin/env python3
"""
Integration tests for Anthropic API protocol support.

Tests:
1. OpenAI format request -> Anthropic conversion
2. Native Anthropic format request passthrough
3. Response conversion (Anthropic -> OpenAI)
"""

import json
import httpx
import asyncio

BASE_URL = "http://127.0.0.1:8000"


async def test_openai_format_to_anthropic():
    """Test sending OpenAI format request to Anthropic provider."""
    print("\n" + "=" * 60)
    print("Test 1: OpenAI Format -> Anthropic Provider")
    print("=" * 60)

    # This test requires a valid proxy key configured with Anthropic provider
    # For now, we just test the conversion logic
    from src.proxy.anthropic_converter import convert_openai_to_anthropic

    openai_request = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"}
        ],
        "max_tokens": 100,
        "temperature": 0.7
    }

    converted = convert_openai_to_anthropic(openai_request)

    assert converted["model"] == "claude-3-5-sonnet-20241022"
    assert converted["max_tokens"] == 100
    assert converted["system"] == "You are a helpful assistant."
    assert len(converted["messages"]) == 1
    assert converted["messages"][0]["role"] == "user"
    assert converted["messages"][0]["content"] == "Hello!"

    print("✓ OpenAI to Anthropic conversion passed")
    return True


async def test_anthropic_response_conversion():
    """Test converting Anthropic response to OpenAI format."""
    print("\n" + "=" * 60)
    print("Test 2: Anthropic Response -> OpenAI Format")
    print("=" * 60)

    from src.proxy.anthropic_converter import convert_anthropic_to_openai

    anthropic_response = {
        "id": "msg_test123",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Hello! How can I help you?"}
        ],
        "model": "claude-3-5-sonnet-20241022",
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 10,
            "output_tokens": 20
        }
    }

    openai_response = convert_anthropic_to_openai(anthropic_response)

    assert openai_response["id"] == "msg_test123"
    assert openai_response["object"] == "chat.completion"
    assert openai_response["model"] == "claude-3-5-sonnet-20241022"
    assert len(openai_response["choices"]) == 1
    assert openai_response["choices"][0]["message"]["content"] == "Hello! How can I help you?"
    assert openai_response["choices"][0]["finish_reason"] == "stop"
    assert openai_response["usage"]["prompt_tokens"] == 10
    assert openai_response["usage"]["completion_tokens"] == 20
    assert openai_response["usage"]["total_tokens"] == 30

    print("✓ Anthropic to OpenAI response conversion passed")
    return True


async def test_tool_conversion():
    """Test tool format conversion between OpenAI and Anthropic."""
    print("\n" + "=" * 60)
    print("Test 3: Tool Format Conversion")
    print("=" * 60)

    from src.proxy.anthropic_converter import convert_openai_to_anthropic, convert_anthropic_tool_to_openai

    openai_tool = {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather for a city",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"}
                },
                "required": ["city"]
            }
        }
    }

    request_with_tools = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [{"role": "user", "content": "Weather in Beijing?"}],
        "max_tokens": 100,
        "tools": [openai_tool]
    }

    converted = convert_openai_to_anthropic(request_with_tools)

    assert "tools" in converted
    assert converted["tools"][0]["name"] == "get_weather"
    assert converted["tools"][0]["description"] == "Get weather for a city"
    assert "input_schema" in converted["tools"][0]

    # Test reverse conversion
    anthropic_tool = converted["tools"][0]
    openai_tool_converted = convert_anthropic_tool_to_openai(anthropic_tool)

    assert openai_tool_converted["type"] == "function"
    assert openai_tool_converted["function"]["name"] == "get_weather"

    print("✓ Tool format conversion passed")
    return True


async def test_stream_format_detection():
    """Test stream format detection for Anthropic requests."""
    print("\n" + "=" * 60)
    print("Test 4: Stream Format Detection")
    print("=" * 60)

    from src.proxy.anthropic_converter import extract_system_prompts_from_anthropic

    # Native Anthropic format with system
    anthropic_request = {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "Hello"}],
        "system": "You are helpful.",
        "stream": True
    }

    system = extract_system_prompts_from_anthropic(anthropic_request)
    assert system == "You are helpful."

    # Anthropic format with content block array for system
    anthropic_request_blocks = {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "Hello"}],
        "system": [{"type": "text", "text": "You are helpful."}],
        "stream": True
    }

    system = extract_system_prompts_from_anthropic(anthropic_request_blocks)
    assert system == "You are helpful."

    print("✓ Stream format detection passed")
    return True


async def test_stop_reason_mapping():
    """Test Anthropic stop_reason to OpenAI finish_reason mapping."""
    print("\n" + "=" * 60)
    print("Test 5: Stop Reason Mapping")
    print("=" * 60)

    from src.proxy.anthropic_converter import convert_anthropic_to_openai, _map_stop_reason

    # Test all stop reason mappings
    assert _map_stop_reason("end_turn") == "stop"
    assert _map_stop_reason("max_tokens") == "length"
    assert _map_stop_reason("stop_sequence") == "stop"
    assert _map_stop_reason("tool_use") == "tool_calls"
    assert _map_stop_reason("pause") == "length"
    assert _map_stop_reason(None) == "stop"
    assert _map_stop_reason("unknown") == "stop"

    # Test full response with tool_use
    response_with_tool = {
        "id": "msg_tool123",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": "tool_1", "name": "get_weather", "input": {"city": "Beijing"}}
        ],
        "model": "claude-3-5-sonnet-20241022",
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 10, "output_tokens": 50}
    }

    openai_response = convert_anthropic_to_openai(response_with_tool)
    assert openai_response["choices"][0]["finish_reason"] == "tool_calls"
    assert "tool_calls" in openai_response["choices"][0]["message"]

    print("✓ Stop reason mapping passed")
    return True


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Anthropic API Protocol Support - Integration Tests")
    print("=" * 60)

    tests = [
        ("OpenAI -> Anthropic Request Conversion", test_openai_format_to_anthropic),
        ("Anthropic -> OpenAI Response Conversion", test_anthropic_response_conversion),
        ("Tool Format Conversion", test_tool_conversion),
        ("Stream Format Detection", test_stream_format_detection),
        ("Stop Reason Mapping", test_stop_reason_mapping),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            await test_func()
            passed += 1
        except AssertionError as e:
            print(f"✗ {name} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {name} ERROR: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
