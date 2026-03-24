"""API Proxy handler - intercept and forward LLM API requests."""

from datetime import datetime
from typing import Any

import httpx

from src.auth.middleware import ProxyAuthResult
from src.recorder.recorder import RequestRecorder


class ProxyHandler:
    """Handle proxying of LLM API requests."""

    # Provider base URLs
    PROVIDER_BASE_URLS = {
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com/v1",
        "gemini": "https://generativelanguage.googleapis.com/v1beta",
        "azure_openai": "https://{resource}.openai.azure.com/openai/deployments/{deployment}",
    }

    def __init__(
        self,
        auth_result: ProxyAuthResult,
        recorder: RequestRecorder,
        http_client: httpx.AsyncClient
    ):
        self.auth_result = auth_result
        self.recorder = recorder
        self.http_client = http_client
        self.start_time: datetime | None = None
        self.first_token_time: datetime | None = None

    async def forward_request(
        self,
        path: str,
        method: str,
        headers: dict[str, str],
        body: dict[str, Any]
    ) -> tuple[int, dict[str, str], Any]:
        """Forward request to the LLM provider.

        Args:
            path: API path (e.g., /chat/completions)
            method: HTTP method
            headers: Request headers
            body: Request body

        Returns:
            Tuple of (status_code, response_headers, response_body)
        """
        self.start_time = datetime.now()

        # Build target URL based on provider
        base_url = self._get_base_url()
        target_url = f"{base_url}{path}"

        # Prepare headers - replace auth header with provider key
        proxy_headers = self._prepare_headers(headers)

        # Record request start
        await self.recorder.record_request_start(
            proxy_key_id=self.auth_result.proxy_key_id,
            path=path,
            method=method,
            model=body.get("model"),
            provider=self.auth_result.provider_type,
            body=body,
            start_time=self.start_time
        )

        try:
            # Check if streaming
            is_stream = body.get("stream", False)

            if is_stream:
                # Handle streaming response
                status_code, resp_headers, response_body = await self._forward_stream_request(
                    target_url, method, proxy_headers, body
                )
            else:
                # Handle regular request
                status_code, resp_headers, response_body = await self._forward_regular_request(
                    target_url, method, proxy_headers, body
                )

            return status_code, dict(resp_headers), response_body

        except httpx.TimeoutException as e:
            # Handle timeout
            await self.recorder.record_error(
                status_code=504,
                error_message=f"Request timeout: {str(e)}"
            )
            raise
        except Exception as e:
            await self.recorder.record_error(
                status_code=502,
                error_message=f"Proxy error: {str(e)}"
            )
            raise

    def _get_base_url(self) -> str:
        """Get the base URL for the provider."""
        # Use custom base_url if configured
        if self.auth_result.base_url:
            return self.auth_result.base_url

        provider = self.auth_result.provider_type
        base_url = self.PROVIDER_BASE_URLS.get(provider)

        if not base_url:
            raise ValueError(f"Unknown provider: {provider}")

        return base_url

    def _prepare_headers(self, original_headers: dict[str, str]) -> dict[str, str]:
        """Prepare headers for the provider request."""
        # Copy headers and remove proxy-specific headers
        headers = {
            k: v for k, v in original_headers.items()
            if not k.lower().startswith("x-proxy-")
        }

        # Set provider-specific auth header
        provider = self.auth_result.provider_type
        api_key = self.auth_result.provider_key

        if provider == "anthropic":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
        elif provider in ("openai", "azure_openai"):
            headers["Authorization"] = f"Bearer {api_key}"
        elif provider == "gemini":
            # Gemini uses query param for API key
            pass
        else:
            headers["Authorization"] = f"Bearer {api_key}"

        return headers

    async def _forward_regular_request(
        self,
        url: str,
        method: str,
        headers: dict[str, str],
        body: dict[str, Any]
    ) -> tuple[int, dict, Any]:
        """Forward a regular (non-streaming) request."""
        response = await self.http_client.request(
            method=method,
            url=url,
            headers=headers,
            json=body,
            timeout=60.0
        )

        end_time = datetime.now()
        self.first_token_time = end_time  # For non-streaming, first token = complete

        response_body = response.json() if response.content else {}

        # Record the response
        await self.recorder.record_response(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=response_body,
            end_time=end_time,
            first_token_time=self.first_token_time
        )

        return response.status_code, response.headers, response_body

    async def _forward_stream_request(
        self,
        url: str,
        method: str,
        headers: dict[str, str],
        body: dict[str, Any]
    ) -> tuple[int, dict, Any]:
        """Forward a streaming request and capture the full response."""
        # For streaming, we need to capture all chunks and reconstruct the response
        # while also streaming to the client

        response = await self.http_client.stream(
            method=method,
            url=url,
            headers=headers,
            json=body,
            timeout=60.0
        )

        # Record timing
        end_time = datetime.now()

        # For streaming, we'll record minimal info now
        # The full body will be recorded when the stream completes
        await self.recorder.record_stream_start(
            status_code=response.status_code,
            headers=dict(response.headers),
            end_time=end_time
        )

        return response.status_code, dict(response.headers), {"stream": True}

    async def extract_usage_from_response(
        self,
        response_body: Any,
        provider: str
    ) -> dict[str, int]:
        """Extract token usage from response."""
        usage = response_body.get("usage", {})

        return {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0)
        }
