"""Protocol parsers for LLM streaming responses.

This module provides a pluggable architecture for parsing streaming responses
from different LLM providers (OpenAI, Anthropic, etc.) using the Strategy
and Factory design patterns.

Example usage:
    from src.proxy.protocols import StreamParserFactory

    parser = StreamParserFactory.create("anthropic")
    parsed = parser.parse_chunks(chunks)
    response = parser.to_openai_format(parsed)
"""

from .base import BaseStreamParser, ParsedResponse
from .factory import StreamParserFactory
from .registry import ProtocolRegistry

__all__ = [
    "BaseStreamParser",
    "ParsedResponse",
    "ProtocolRegistry",
    "StreamParserFactory",
]
