# Protocol Plugins

This directory is reserved for third-party protocol parsers that can be added as plugins.

## How to Add a New Protocol Parser

To add support for a new LLM provider (e.g., Gemini, Cohere, Mistral):

### Step 1: Create a new parser module

Create a new file `src/proxy/protocols/<provider>.py`:

```python
"""Gemini protocol stream parser."""

import json
import logging
from typing import Any

from .base import BaseStreamParser, ParsedResponse
from .registry import ProtocolRegistry

logger = logging.getLogger(__name__)


class GeminiParser(BaseStreamParser):
    """Parser for Gemini-style streaming responses."""

    protocol_name = "gemini"

    def parse_chunks(self, chunks: list[bytes]) -> ParsedResponse:
        """Parse Gemini-style SSE chunks.

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

        # Implement Gemini-specific parsing logic here
        # Gemini SSE format may differ from OpenAI/Anthropic

        content_parts: list[str] = []
        usage: dict[str, Any] = {}
        response_id: str | None = None
        model: str | None = None
        finish_reason = "stop"

        # Parse SSE chunks...
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload == "[DONE]" or not payload:
                    continue
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                # Extract content, usage, model, etc.
                response_id = response_id or obj.get("id")
                model = model or obj.get("model")
                # ... more parsing logic

        return ParsedResponse(
            content="".join(content_parts) if content_parts else "",
            usage=self.normalize_usage(usage),
            model=model,
            finish_reason=finish_reason,
            metadata={"id": response_id},
        )

    def _empty_response(self) -> ParsedResponse:
        """Return empty response for error cases."""
        return ParsedResponse(
            content="",
            usage={"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
            model=None,
            finish_reason="stop",
            metadata={},
        )


# Auto-register this parser at module load time
ProtocolRegistry().register("gemini", GeminiParser)
```

### Step 2: Register the provider mapping

Add the provider to protocol mapping in `src/proxy/protocols/factory.py`:

```python
PROVIDER_TO_PROTOCOL: dict[str, str] = {
    "openai": "openai",
    "azure_openai": "openai",
    "anthropic": "anthropic",
    "dashscope_anthropic": "anthropic",
    "gemini": "gemini",  # Add new mapping here
    # ... more providers
}
```

### Step 3: Update auto-discover (optional)

If you want the parser to be auto-discovered, add the import in `src/proxy/protocols/registry.py`:

```python
def auto_discover(self) -> None:
    """Auto-discover and register built-in protocol parsers."""
    from . import anthropic  # noqa
    from . import openai  # noqa
    from . import gemini  # noqa  # Add new import here
```

## Testing Your Parser

After creating your parser, test it:

```python
from src.proxy.protocols import StreamParserFactory

parser = StreamParserFactory.create("gemini")
parsed = parser.parse_chunks(mock_chunks)
response = parser.to_openai_format(parsed)
```

## Plugin Architecture

Parsers are automatically registered at module load time via the `ProtocolRegistry().register()` call at the bottom of each parser module.

The `ProtocolRegistry` is a singleton that maintains the mapping between protocol names and their parser classes.

## File Structure

```
src/proxy/protocols/
├── __init__.py             # Module exports
├── base.py                 # BaseStreamParser ABC and ParsedResponse dataclass
├── registry.py             # ProtocolRegistry singleton
├── factory.py              # StreamParserFactory with provider mappings
├── openai.py               # OpenAI parser implementation
├── anthropic.py            # Anthropic parser implementation
├── gemini.py               # Your new Gemini parser (example)
└── plugins/
    └── README.md           # This file
```

## Best Practices

1. **Inherit from BaseStreamParser**: Always extend the abstract base class
2. **Implement parse_chunks()**: This is the only required method
3. **Use normalize_usage()**: Leverage the base class method for consistent usage format
4. **Auto-register**: Call `ProtocolRegistry().register()` at module bottom
5. **Handle errors gracefully**: Return `_empty_response()` on parse failures
6. **Preserve metadata**: Store provider-specific fields in `metadata` dict
7. **Map finish reasons**: Convert provider-specific stop reasons to OpenAI format
