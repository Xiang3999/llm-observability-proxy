"""Factory for creating protocol-specific stream parsers."""

from typing import Optional

from .registry import ProtocolRegistry
from .base import BaseStreamParser

# Provider-to-protocol mapping
# Multiple providers can map to the same protocol parser
PROVIDER_TO_PROTOCOL: dict[str, str] = {
    "openai": "openai",
    "azure_openai": "openai",
    "anthropic": "anthropic",
    "dashscope_anthropic": "anthropic",
    # Future providers can be added here:
    # "gemini": "gemini",
    # "cohere": "cohere",
    # "mistral": "mistral",
}


class StreamParserFactory:
    """Factory for creating protocol-specific stream parsers.

    Usage:
        parser = StreamParserFactory.create("anthropic")
        parsed = parser.parse_chunks(chunks)
        response = parser.to_openai_format(parsed)
    """

    _registry: Optional[ProtocolRegistry] = None

    @classmethod
    def get_registry(cls) -> ProtocolRegistry:
        """Get or initialize the protocol registry."""
        if cls._registry is None:
            cls._registry = ProtocolRegistry()
            cls._registry.auto_discover()
        return cls._registry

    @classmethod
    def create(cls, provider: str) -> BaseStreamParser:
        """Create parser based on provider name.

        Args:
            provider: Provider name (e.g., "openai", "anthropic", "azure_openai")

        Returns:
            Parser instance for the provider's protocol

        Raises:
            ValueError: If provider is not mapped to any protocol
        """
        protocol_name = PROVIDER_TO_PROTOCOL.get(provider, provider)
        return cls.get_registry().get_parser(protocol_name)

    @classmethod
    def register_provider(cls, provider: str, protocol_name: str) -> None:
        """Register a new provider-to-protocol mapping.

        Args:
            provider: Provider name
            protocol_name: Protocol name to map to
        """
        PROVIDER_TO_PROTOCOL[provider] = protocol_name
