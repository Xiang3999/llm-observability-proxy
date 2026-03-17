"""Request recorder - record API requests and responses."""

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.request_log import RequestLog


class RequestRecorder:
    """Record API requests and responses for observability."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.current_request: RequestLog | None = None

    async def record_request_start(
        self,
        proxy_key_id: str,
        path: str,
        method: str,
        model: str | None,
        provider: str,
        body: dict[str, Any],
        start_time: datetime,
        headers: dict[str, str] | None = None,
        request_log_id: str | None = None  # Optional pre-generated ID for streaming
    ) -> RequestLog:
        """Record the start of a request."""
        # Extract user_id, session_id and properties from body if present
        user_id = None
        session_id = None
        properties = {}

        if isinstance(body, dict):
            user_id = body.get("user")
            session_id = body.get("session_id")  # Extract session_id directly
            # Extract custom properties (Helicone-style)
            for key, value in body.items():
                if key.startswith("helicone_property_"):
                    properties[key.replace("helicone_property_", "")] = value

        request_log = RequestLog(
            id=request_log_id,  # Use pre-generated ID if provided
            proxy_key_id=proxy_key_id,
            request_path=path,
            method=method,
            model=model,
            provider=provider,
            created_at=start_time,
            user_id=user_id,
            session_id=session_id,  # Store session_id
            properties=properties,
            request_body=body,  # Store inline for now
            request_headers=headers  # Store request headers
        )

        self.db.add(request_log)
        await self.db.flush()
        try:
            await self.db.refresh(request_log)
        except Exception:
            # In-memory SQLite or some drivers may not support refresh; we already have id from default
            pass

        self.current_request = request_log
        return request_log

    async def record_response(
        self,
        status_code: int,
        headers: dict[str, str],
        body: Any,
        end_time: datetime,
        first_token_time: datetime | None = None
    ) -> None:
        """Record the response for the current request."""
        if not self.current_request:
            return

        request = self.current_request
        request.status_code = status_code
        request.completed_at = end_time
        request.response_body = body
        request.response_headers = headers  # Store response headers

        # Calculate latency
        if request.created_at:
            request.total_latency_ms = int(
                (end_time - request.created_at).total_seconds() * 1000
            )

        # Calculate time to first token
        if first_token_time and request.created_at:
            request.time_to_first_token_ms = int(
                (first_token_time - request.created_at).total_seconds() * 1000
            )

        # Extract token usage from response
        if isinstance(body, dict):
            usage = body.get("usage", {})
            request.prompt_tokens = usage.get("prompt_tokens")
            request.completion_tokens = usage.get("completion_tokens")
            request.total_tokens = usage.get("total_tokens")

            # Extract Bailian/OpenAI compatible cached tokens
            # From usage.prompt_tokens_details.cached_tokens or usage.usage_details.cached_tokens
            prompt_details = usage.get("prompt_tokens_details", {}) or usage.get("usage_details", {})
            if isinstance(prompt_details, dict):
                cached_tokens = prompt_details.get("cached_tokens", 0)
                if cached_tokens and request.cache_read_tokens is None:
                    request.cache_read_tokens = cached_tokens
                # DashScope: cache_creation may be nested under prompt_tokens_details
                if request.cache_creation_tokens is None:
                    cc = prompt_details.get("cache_creation")
                    if isinstance(cc, dict) and cc.get("cache_creation_input_tokens") is not None:
                        request.cache_creation_tokens = cc.get("cache_creation_input_tokens")

            # Extract model from response if not in request
            if not request.model:
                request.model = body.get("model")

            # Extract Anthropic-specific cache metrics (top-level)
            # From usage object: cache_read_input_tokens, cache_creation_input_tokens
            if usage.get("cache_read_input_tokens") is not None:
                request.cache_read_tokens = usage.get("cache_read_input_tokens")
            if usage.get("cache_creation_input_tokens") is not None:
                request.cache_creation_tokens = usage.get("cache_creation_input_tokens")

            # Extract detailed usage breakdown
            usage_breakdown = {
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
            }
            # Filter out None values
            request.usage_breakdown = {k: v for k, v in usage_breakdown.items() if v is not None}

            # Extract Anthropic metadata from headers
            anthropic_meta = {}
            if headers:
                # x-anthropic-billing-header: cc_version=2.1.70.f29; cc_entrypoint=cli; cch=36347
                billing_header = headers.get("x-anthropic-billing-header", "")
                if billing_header:
                    for part in billing_header.split(";"):
                        part = part.strip()
                        if "=" in part:
                            key, value = part.split("=", 1)
                            anthropic_meta[key.strip()] = value.strip()
                # x-anthropic-cache-header
                cache_header = headers.get("x-anthropic-cache-header", "")
                if cache_header:
                    anthropic_meta["cache_header"] = cache_header

            if anthropic_meta:
                request.anthropic_metadata = anthropic_meta

        await self.db.flush()

    async def record_error(
        self,
        status_code: int,
        error_message: str
    ) -> None:
        """Record an error for the current request."""
        if not self.current_request:
            return

        request = self.current_request
        request.status_code = status_code
        request.error_message = error_message
        request.completed_at = datetime.now()

        if request.created_at:
            request.total_latency_ms = int(
                (request.completed_at - request.created_at).total_seconds() * 1000
            )

        await self.db.flush()

    async def record_stream_start(
        self,
        status_code: int,
        headers: dict[str, str],
        end_time: datetime
    ) -> None:
        """Record the start of a streaming response."""
        if not self.current_request:
            return

        request = self.current_request
        request.status_code = status_code

        if request.created_at:
            request.total_latency_ms = int(
                (end_time - request.created_at).total_seconds() * 1000
            )

        await self.db.flush()

    async def finalize(self) -> RequestLog | None:
        """Finalize and commit the current request."""
        if self.current_request:
            request = self.current_request
            self.current_request = None
            return request
        return None
