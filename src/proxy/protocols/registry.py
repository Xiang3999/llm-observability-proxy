"""Protocol registry for stream parsers."""

from typing import Optional, Type

from .base import BaseStreamParser


class ProtocolRegistry:
    """Singleton registry for protocol parsers.

    Manages the mapping between protocol names and their parser implementations.
    Supports dynamic registration and retrieval of protocol-specific parsers.
    """

    _instance: Optional["ProtocolRegistry"] = None
    _parsers: dict[str, Type[BaseStreamParser]] = {}

    def __new__(cls) -> "ProtocolRegistry":
        """Ensure only one instance exists (Singleton pattern)."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(self, protocol_name: str, parser_class: Type[BaseStreamParser]) -> None:
        """Register a parser class for a protocol.

        Args:
            protocol_name: Name of the protocol (e.g., "openai", "anthropic")
            parser_class: Parser class that implements BaseStreamParser
        """
        self._parsers[protocol_name] = parser_class

    def get_parser(self, protocol_name: str) -> BaseStreamParser:
        """Get parser instance for a protocol.

        Args:
            protocol_name: Name of the protocol

        Returns:
            Parser instance for the specified protocol

        Raises:
            ValueError: If protocol is not registered
        """
        parser_class = self._parsers.get(protocol_name)
        if parser_class is None:
            raise ValueError(f"Unknown protocol: {protocol_name}")
        return parser_class()

    def list_protocols(self) -> list[str]:
        """List all registered protocols.

        Returns:
            List of registered protocol names
        """
        return list(self._parsers.keys())

    def auto_discover(self) -> None:
        """Auto-discover and register built-in protocol parsers.

        Importing protocol modules triggers their __init__ which
        automatically registers them with the registry.
        """
        # Import built-in protocol modules to trigger auto-registration
        from . import anthropic  # noqa
        from . import openai  # noqa
