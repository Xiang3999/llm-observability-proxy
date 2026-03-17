"""LLM API Proxy routes - Optimized for minimal latency."""

import asyncio
import json
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse

from src.auth.middleware import ProxyAuthResult, get_proxy_auth
from src.cache.semantic_cache import SemanticCache
from src.config import settings
from src.proxy.protocols import StreamParserFactory
from src.recorder.recorder import RequestRecorder

router = APIRouter(tags=["Proxy"])

# Global semantic cache instance (initialized once)
_semantic_cache: SemanticCache | None = None

# Global HTTP client with connection pooling for better performance
_http_client: httpx.AsyncClient | None = None

# Model mapping cache for Anthropic protocol (source_model -> target_model)
# TTL: 60 seconds, to balance latency and config freshness
_model_mapping_cache: dict[str, tuple[str, float]] = {}
_MODEL_MAPPING_CACHE_TTL = 60.0

logger = structlog.get_logger(__name__)


def clear_model_mapping_cache():
    """Clear the model mapping cache. Call when mappings are updated."""
    global _model_mapping_cache
    _model_mapping_cache.clear()
    logger.info("model mapping cache cleared")


def get_semantic_cache() -> SemanticCache:
    """Get or create the global semantic cache instance."""
    global _semantic_cache
    if _semantic_cache is None:
        _semantic_cache = SemanticCache(
            enabled=settings.cache_enabled,
            similarity_threshold=settings.cache_similarity_threshold,
            ttl_seconds=settings.cache_ttl_seconds,
            max_size=settings.cache_max_size
        )
    return _semantic_cache


def get_http_client() -> httpx.AsyncClient:
    """Global HTTP client with aggressive connection pooling (minimize TLS + connect latency)."""
    global _http_client
    if _http_client is None:
        timeout = settings.upstream_timeout_seconds
        _http_client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(
                max_keepalive_connections=100,
                max_connections=200,
                keepalive_expiry=120.0,  # 保持连接更久，减少冷启动
            ),
        )
    return _http_client


# Chunk size when streaming request body to upstream (mimics direct client chunked upload)
_STREAM_BODY_CHUNK_SIZE = 16384  # Increased from 8192 for better throughput


async def _stream_body_chunks(body: dict):
    """Async generator: serialize body to JSON and yield in chunks.

    Optimizations:
    - Use fastjson-like approach: encode once, yield slices
    - Larger chunk size reduces generator overhead
    """
    # Pre-encode entire JSON (faster than incremental encoding for typical sizes)
    data = json.dumps(body, separators=(',', ':')).encode("utf-8")
    # separators=(',', ':') removes spaces for ~10% smaller payload
    for i in range(0, len(data), _STREAM_BODY_CHUNK_SIZE):
        yield data[i : i + _STREAM_BODY_CHUNK_SIZE]


async def _get_mapped_model(source_model: str) -> str:
    """Get mapped target model for Anthropic protocol only.

    Supports three types of mappings (in priority order):
    1. Exact match: "claude-3-5-sonnet" → "glm-5"
    2. Prefix match: "claude-*" → matches any model starting with "claude-"
    3. Wildcard: "*" → matches all unconfigured models

    Uses in-memory cache with TTL to avoid DB hits on every request.
    Returns source_model if no mapping exists.
    """
    global _model_mapping_cache

    now = time.monotonic()

    # Check cache first for exact match
    cached = _model_mapping_cache.get(source_model)
    if cached is not None:
        target_model, expiry = cached
        if now < expiry:
            return target_model
        # Expired, remove from cache
        _model_mapping_cache.pop(source_model, None)

    # Query database for all active mappings
    try:
        from sqlalchemy import select
        from src.models.database import AsyncSessionLocal
        from src.models.model_mapping import ModelMapping

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ModelMapping).where(ModelMapping.is_active == True)
            )
            all_mappings = result.scalars().all()

            # Priority 1: Exact match
            for mapping in all_mappings:
                if mapping.source_model == source_model:
                    _model_mapping_cache[source_model] = (mapping.target_model, now + _MODEL_MAPPING_CACHE_TTL)
                    logger.debug("model mapping applied (exact)", source=source_model, target=mapping.target_model)
                    return mapping.target_model

            # Priority 2: Prefix match (e.g., "claude-*" matches "claude-3-5-sonnet")
            # Sort by source_model length descending to match longest prefix first
            prefix_mappings = [m for m in all_mappings if m.source_model.endswith("*") and m.source_model != "*"]
            prefix_mappings.sort(key=lambda m: len(m.source_model), reverse=True)

            for mapping in prefix_mappings:
                prefix = mapping.source_model[:-1]  # Remove the "*"
                if source_model.startswith(prefix):
                    _model_mapping_cache[source_model] = (mapping.target_model, now + _MODEL_MAPPING_CACHE_TTL)
                    logger.debug("model mapping applied (prefix)", source=source_model, pattern=mapping.source_model, target=mapping.target_model)
                    return mapping.target_model

            # Priority 3: Wildcard match ("*" matches everything)
            for mapping in all_mappings:
                if mapping.source_model == "*":
                    _model_mapping_cache[source_model] = (mapping.target_model, now + _MODEL_MAPPING_CACHE_TTL)
                    logger.debug("model mapping applied (wildcard)", source=source_model, target=mapping.target_model)
                    return mapping.target_model

    except Exception as e:
        logger.warning("model mapping lookup failed", error=str(e))

    # No mapping found, cache the negative result
    _model_mapping_cache[source_model] = (source_model, now + _MODEL_MAPPING_CACHE_TTL)
    return source_model


# Provider base URLs
PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}


def _safe_body_for_db(obj: dict[str, Any] | None) -> dict:
    """Return a JSON-serializable copy for DB (request_body/response_body columns). Avoids serialization errors."""
    if obj is None:
        return {}
    try:
        return json.loads(json.dumps(obj, default=str))
    except (TypeError, ValueError):
        return {}


def _sum_detail_tokens(details: dict) -> int | None:
    """Sum token fields from DashScope prompt_tokens_details or completion_tokens_details."""
    if not isinstance(details, dict):
        return None
    total = 0
    for key in (
        "text_tokens", "image_tokens", "video_tokens", "audio_tokens",
        "cached_tokens", "reasoning_tokens",
        "cache_creation_input_tokens", "ephemeral_5m_input_tokens",
    ):
        v = details.get(key)
        if isinstance(v, int):
            total += v
    return total if total else None


def _normalize_usage(usage: dict) -> dict:
    """Normalize usage: OpenAI/DashScope fields, usage_details, prompt_tokens_details/completion_tokens_details."""
    if not usage:
        return {}
    u = dict(usage)
    # Top-level aliases (DashScope: input_tokens / output_tokens)
    u.setdefault("prompt_tokens", u.get("input_tokens"))
    u.setdefault("completion_tokens", u.get("output_tokens"))
    # usage_details or prompt_tokens_details
    details = u.get("usage_details") or u.get("prompt_tokens_details") or {}
    if isinstance(details, dict):
        u.setdefault("prompt_tokens", details.get("input_tokens") or details.get("prompt_tokens"))
        u.setdefault("completion_tokens", details.get("output_tokens") or details.get("completion_tokens"))
    # DashScope stream: usage only in last chunk; may have only prompt_tokens_details / completion_tokens_details
    prompt_details = u.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        if u.get("prompt_tokens") is None:
            s = _sum_detail_tokens(prompt_details)
            if s is not None:
                u["prompt_tokens"] = s
        # DashScope: cached_tokens in prompt_tokens_details -> cache_read_tokens
        if u.get("cache_read_tokens") is None and u.get("cache_read_input_tokens") is None:
            ct = prompt_details.get("cached_tokens")
            if ct is not None:
                u.setdefault("cache_read_tokens", ct)
                u.setdefault("cache_read_input_tokens", ct)
    if u.get("cache_read_input_tokens") is not None and u.get("cache_read_tokens") is None:
        u.setdefault("cache_read_tokens", u.get("cache_read_input_tokens"))
    comp_details = u.get("completion_tokens_details")
    if isinstance(comp_details, dict) and u.get("completion_tokens") is None:
        s = _sum_detail_tokens(comp_details)
        if s is not None:
            u["completion_tokens"] = s
    if u.get("prompt_tokens") is not None and u.get("completion_tokens") is not None and u.get("total_tokens") is None:
        u["total_tokens"] = u["prompt_tokens"] + u["completion_tokens"]
    return u


def _convert_anthropic_to_openai_format(response: dict) -> dict:
    """Convert Anthropic/DashScope Anthropic response to OpenAI-compatible format.

    Anthropic format:
    {
        "id": "msg_xxx",
        "model": "glm-5",
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "...", "signature": "..."},
            {"type": "text", "text": "..."}
        ],
        "usage": {"input_tokens": 10, "output_tokens": 20},
        "stop_reason": "end_turn"
    }

    OpenAI format:
    {
        "id": "chatcmpl_xxx",
        "model": "glm-5",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "...",
                "reasoning_content": "..."  // if thinking present
            },
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    }
    """
    # Extract content parts
    content_text = ""
    reasoning_content = ""
    content_array = response.get("content", [])

    if isinstance(content_array, list):
        for item in content_array:
            if isinstance(item, dict):
                content_type = item.get("type", "")
                if content_type == "text":
                    content_text += item.get("text", "")
                elif content_type == "thinking":
                    reasoning_content += item.get("thinking", "")
    elif isinstance(content_array, str):
        content_text = content_array

    # Build OpenAI format response
    input_tokens = response.get("usage", {}).get("input_tokens", 0) or response.get("usage", {}).get("prompt_tokens", 0)
    output_tokens = response.get("usage", {}).get("output_tokens", 0) or response.get("usage", {}).get("completion_tokens", 0)

    result = {
        "id": response.get("id", ""),
        "model": response.get("model", ""),
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": content_text,
            },
            "finish_reason": response.get("stop_reason", "stop")
        }],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }

    # Add reasoning_content if present
    if reasoning_content:
        result["choices"][0]["message"]["reasoning_content"] = reasoning_content

    return result


async def create_stream_request_log_async(
    proxy_key_id: str,
    path: str,
    method: str,
    model: str | None,
    provider: str,
    body: dict[str, Any] | None,
    start_time: datetime,
    status_code: int,
    request_headers: dict[str, Any] | None = None,
) -> str | None:
    """Create request log for a stream; returns request_log id for later update when stream completes."""
    from src.models.database import AsyncSessionLocal

    body = _safe_body_for_db(body or {})
    async with AsyncSessionLocal() as session:
        try:
            recorder = RequestRecorder(session)
            await recorder.record_request_start(
                proxy_key_id=proxy_key_id,
                path=path,
                method=method,
                model=model,
                provider=provider,
                body=body,
                start_time=start_time,
                headers=request_headers,
            )
            end_time = datetime.now()
            await recorder.record_response(
                status_code=status_code,
                headers={},
                body={"stream": True},
                end_time=end_time,
                first_token_time=end_time,
            )
            req = await recorder.finalize()
            await session.commit()
            return req.id if req else None
        except Exception as e:
            await session.rollback()
            logger.error("Create stream log failed: %s", e, exc_info=True)
            return None


async def update_stream_response_async(
    request_log_id: str,
    chunks: list[bytes],
    end_time: datetime,
    provider: str = "openai",
    first_chunk_time: datetime | None = None,
):
    """Update an existing stream request log with reconstructed response from chunks."""
    from sqlalchemy import select

    from src.models.database import AsyncSessionLocal
    from src.models.request_log import RequestLog

    # Use factory to create parser based on provider
    parser = StreamParserFactory.create(provider)
    parsed = parser.parse_chunks(chunks)
    response_body = parser.to_openai_format(parsed)

    # Debug: full reconstructed response body for stream (set LOG_LEVEL=DEBUG); focus on usage / cache
    usage_debug = response_body.get("usage") if isinstance(response_body, dict) else None
    logger.debug(
        "stream_update_log",
        request_log_id=request_log_id,
        response_usage=usage_debug,
        response_usage_keys=list(usage_debug.keys()) if isinstance(usage_debug, dict) else None,
        prompt_tokens_details=usage_debug.get("prompt_tokens_details") if isinstance(usage_debug, dict) else None,
        completion_tokens_details=usage_debug.get("completion_tokens_details") if isinstance(usage_debug, dict) else None,
    )
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(RequestLog).where(RequestLog.id == request_log_id))
            log = result.scalar_one_or_none()
            if not log:
                return
            log.completed_at = end_time
            # Time to first token = from request start until first response chunk received
            if first_chunk_time and log.created_at:
                log.time_to_first_token_ms = int(
                    (first_chunk_time - log.created_at).total_seconds() * 1000
                )
            log.response_body = response_body
            if isinstance(response_body, dict):
                usage = response_body.get("usage") or {}
                log.prompt_tokens = usage.get("prompt_tokens")
                log.completion_tokens = usage.get("completion_tokens")
                log.total_tokens = usage.get("total_tokens")
                if not log.model:
                    log.model = response_body.get("model")
                # Cache tokens: Anthropic (cache_read_input_tokens, cache_creation_input_tokens) or DashScope (prompt_tokens_details.cached_tokens / cache_creation)
                if usage.get("cache_read_input_tokens") is not None:
                    log.cache_read_tokens = usage.get("cache_read_input_tokens")
                if usage.get("cache_creation_input_tokens") is not None:
                    log.cache_creation_tokens = usage.get("cache_creation_input_tokens")
                prompt_details = usage.get("prompt_tokens_details") or usage.get("usage_details") or {}
                if isinstance(prompt_details, dict):
                    if prompt_details.get("cached_tokens") is not None and log.cache_read_tokens is None:
                        log.cache_read_tokens = prompt_details.get("cached_tokens")
                    if log.cache_creation_tokens is None:
                        cc = prompt_details.get("cache_creation")
                        if isinstance(cc, dict) and cc.get("cache_creation_input_tokens") is not None:
                            log.cache_creation_tokens = cc.get("cache_creation_input_tokens")
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error("Update stream response failed: %s", e, exc_info=True)


async def record_response_async(
    proxy_key_id: str,
    path: str,
    method: str,
    model: str | None,
    provider: str,
    body: dict[str, Any] | None,
    body_bytes: bytes | None,
    start_time: datetime,
    status_code: int,
    response_body: dict,
    request_headers: dict[str, Any] | None = None,
    request_log_id: str | None = None,  # Optional pre-generated ID for streaming
    first_token_time: datetime | None = None,  # Pass None for streaming (TTFT set in update_stream_response_async). Omit for non-streaming to use end_time.
) -> str | None:
    """Record response with its own DB session. Returns request_log id for later update (e.g. stream)."""
    from src.models.database import AsyncSessionLocal

    if body is None and body_bytes:
        try:
            body = json.loads(body_bytes) if body_bytes else {}
        except Exception:
            body = {}
    body = _safe_body_for_db(body or {})
    response_body = _safe_body_for_db(response_body) if isinstance(response_body, dict) else {}

    async with AsyncSessionLocal() as session:
        try:
            recorder = RequestRecorder(session)
            await recorder.record_request_start(
                proxy_key_id=proxy_key_id,
                path=path,
                method=method,
                model=model,
                provider=provider,
                body=body,
                start_time=start_time,
                headers=request_headers,
                request_log_id=request_log_id,  # Use pre-generated ID if provided
            )
            end_time = datetime.now()
            # Streaming (request_log_id set): use first_token_time as-is (None); TTFT set in update_stream_response_async.
            # Non-streaming: use end_time when first_token_time not provided so TTFT = total latency.
            if request_log_id is not None:
                ttft = first_token_time
            else:
                ttft = first_token_time if first_token_time is not None else end_time
            await recorder.record_response(
                status_code=status_code,
                headers={},
                body=response_body,
                end_time=end_time,
                first_token_time=ttft,
            )
            req = await recorder.finalize()
            await session.commit()
            return req.id if req else None
        except Exception as e:
            await session.rollback()
            logger.error("Async recording failed: %s", e, exc_info=True)
            return None


@router.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_request(
    request: Request,
    path: str,
    auth: ProxyAuthResult = Depends(get_proxy_auth),
):
    """Proxy requests to LLM providers with minimal latency.

    Optimizations (Helicone-style):
    1. Auth cache - avoid DB on every request
    2. When cache disabled: no JSON parse on hot path (forward body bytes)
    3. Recording in background with own DB session (never block response)
    4. Connection pooling - reuse TCP/SSL
    """
    start_datetime = datetime.now()
    cache = get_semantic_cache()
    has_body = request.method in ("POST", "PUT", "PATCH")

    # Parse body when present (needed for stream detection and cache/forward)
    body: dict[str, Any] | None = None
    body_bytes: bytes | None = None
    if has_body:
        body = await request.json()
    is_stream = has_body and isinstance(body, dict) and body.get("stream") is True

    # Semantic cache (only when enabled and we have messages; skip for stream)
    if cache.enabled and body and "messages" in body:
        cache_result = await cache.get(
            messages=body.get("messages", []),
            model=body.get("model"),
        )
        if cache_result.hit:
            cached_response = {
                "id": f"cache-{cache_result.model}-{int(datetime.now().timestamp())}",
                "object": "chat.completion",
                "created": int(datetime.now().timestamp()),
                "model": cache_result.model or (body.get("model") if body else None),
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": cache_result.response},
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cache_hit": True,
                },
                "helicone_cache_hit": True,
            }
            asyncio.create_task(
                record_response_async(
                    proxy_key_id=auth.proxy_key_id,
                    path=f"/v1/{path}",
                    method=request.method,
                    model=body.get("model") if body else None,
                    provider=auth.provider_type,
                    body=body,
                    body_bytes=None,
                    start_time=start_datetime,
                    status_code=200,
                    response_body=cached_response,
                )
            )
            return Response(
                content=json.dumps(cached_response),
                status_code=200,
                media_type="application/json",
                headers={
                    "X-Helicone-Cache-Hit": "true",
                    "X-Helicone-Cache-Similarity": str(cache_result.similarity),
                },
            )

    # Build target URL
    if auth.base_url:
        base_url = auth.base_url
    else:
        base_url = PROVIDER_BASE_URLS.get(auth.provider_type)
        if not base_url:
            base_url = f"https://api.{auth.provider_type}.com/v1"

    # Path mapping for different providers
    # OpenAI format: /v1/chat/completions
    # Anthropic format: /v1/messages
    # Only convert for explicit Anthropic endpoints (URLs containing /anthropic path)
    target_path = path
    is_anthropic_format = (
        auth.provider_type in ("anthropic", "dashscope_anthropic") or
        (auth.base_url and "/anthropic" in auth.base_url.lower())
    )
    if is_anthropic_format and path == "chat/completions":
        target_path = "v1/messages"

    target_url = f"{base_url}/{target_path}"
    try:
        target_host = urlparse(target_url).netloc or target_url
    except Exception:
        target_host = "(parse error)"

    # Model mapping: ONLY for Anthropic protocol
    # Maps request model to target model (e.g., claude-3-5-sonnet -> glm-5)
    original_model = body.get("model") if body else None
    if is_anthropic_format and body and original_model:
        mapped_model = await _get_mapped_model(original_model)
        if mapped_model != original_model:
            body["model"] = mapped_model
            logger.info(
                "anthropic model mapped",
                original=original_model,
                mapped=mapped_model,
            )

    logger.info(
        "proxy forward",
        path=path,
        stream=is_stream,
        target_host=target_host,
        provider=auth.provider_type,
        has_base_url=bool(auth.base_url),
    )

    # Headers: drop host/content-length/auth; set provider auth
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in (
            "host",
            "content-length",
            "authorization",
            "helicone-auth",
            "helicone-proxy-key",
        )
    }
    # Ensure JSON when we stream body as chunks (content= generator does not set Content-Type)
    if has_body and "content-type" not in {k.lower() for k in headers}:
        headers["Content-Type"] = "application/json"

    # Set headers based on provider format (not just provider type)
    # Only use Anthropic headers for explicit Anthropic endpoints
    if auth.provider_type == "anthropic" or (auth.base_url and "/anthropic" in auth.base_url.lower()):
        headers["x-api-key"] = auth.provider_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {auth.provider_key}"

    original_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length", "authorization")
    }

    client = get_http_client()

    # --- Streaming: forward chunks to client without buffering (fixes 0.2s vs 4–40s) ---
    if is_stream:
        try:
            stream_timeout = max(120.0, settings.upstream_timeout_seconds)
            queue: asyncio.Queue = asyncio.Queue(maxsize=0)
            chunks_collector: list[bytes] = []
            # Pre-generate request_log_id so stream_worker can use it without awaiting record_response_async
            import uuid
            stream_log_id: str = str(uuid.uuid4())

            upstream_start = time.perf_counter()

            # Ask upstream for usage in stream (e.g. DashScope needs stream_options.include_usage)
            body_with_usage = dict(body)
            if "stream_options" not in body_with_usage:
                body_with_usage["stream_options"] = {}
            if not isinstance(body_with_usage["stream_options"], dict):
                body_with_usage["stream_options"] = {}
            body_with_usage["stream_options"]["include_usage"] = True

            first_chunk_time: datetime | None = None

            async def stream_worker() -> None:
                nonlocal first_chunk_time
                try:
                    # Send body as chunked stream (same as direct client) so upstream does not wait for one big blob
                    async with client.stream(
                        method=request.method,
                        url=target_url,
                        headers=headers,
                        content=_stream_body_chunks(body_with_usage),
                        timeout=stream_timeout,
                    ) as resp:
                        elapsed_ms = (time.perf_counter() - upstream_start) * 1000
                        logger.info(
                            "upstream headers received",
                            path=path,
                            status=resp.status_code,
                            elapsed_ms=round(elapsed_ms),
                        )
                        await queue.put(("meta", resp.status_code, dict(resp.headers)))
                        async for chunk in resp.aiter_bytes():
                            if first_chunk_time is None:
                                first_chunk_time = datetime.now()
                            chunks_collector.append(chunk)
                            await queue.put(("chunk", chunk))
                except Exception as e:
                    elapsed_ms = (time.perf_counter() - upstream_start) * 1000
                    logger.error(
                        "stream worker error",
                        path=path,
                        after_ms=round(elapsed_ms),
                        error=str(e),
                        exc_info=True,
                    )
                    await queue.put(("error", str(e)))
                finally:
                    # Create update task before sending "done" signal (fire-and-forget for latency)
                    # Use pre-generated stream_log_id directly (no need to wait for record_response_async)
                    if chunks_collector:
                        is_anthropic_format = (
                            auth.provider_type in ("anthropic", "dashscope_anthropic") or
                            (auth.base_url and "/anthropic" in auth.base_url.lower())
                        )
                        parser_provider = "anthropic" if is_anthropic_format else auth.provider_type
                        # Fire-and-forget: don't await, let it complete asynchronously
                        asyncio.create_task(
                            update_stream_response_async(
                                stream_log_id,
                                list(chunks_collector),
                                datetime.now(),
                                parser_provider,
                                first_chunk_time=first_chunk_time,
                            )
                        )
                    await queue.put(("done",))
                    # Don't await update task - return immediately for minimal latency
                    # Task will complete in background; logs are best-effort for observability

            async def stream_from_queue():
                while True:
                    item = await queue.get()
                    if item[0] == "done":
                        break
                    if item[0] == "error":
                        yield json.dumps({"error": item[1]}).encode()
                        break
                    if item[0] == "chunk":
                        yield item[1]

            task = asyncio.create_task(stream_worker())
            try:
                first = await asyncio.wait_for(queue.get(), timeout=stream_timeout)
            except asyncio.TimeoutError as err:
                task.cancel()
                elapsed_ms = (time.perf_counter() - upstream_start) * 1000
                logger.error(
                    "stream timeout waiting for upstream headers",
                    path=path,
                    timeout_s=stream_timeout,
                    elapsed_ms=round(elapsed_ms),
                )
                raise httpx.TimeoutException("Stream timeout") from err
            if first[0] == "error":
                return Response(
                    content=json.dumps({"error": first[1]}),
                    status_code=502,
                    media_type="application/json",
                )
            if first[0] != "meta":
                status_code, resp_headers = 200, {}
            else:
                status_code, resp_headers = first[1], first[2]
            # Create log entry asynchronously (fire-and-forget for minimal latency)
            # Use pre-generated stream_log_id so stream_worker can reference it
            # For streaming, time_to_first_token_ms is set later in update_stream_response_async when first chunk is received
            asyncio.create_task(
                record_response_async(
                    proxy_key_id=auth.proxy_key_id,
                    path=f"/v1/{path}",
                    method=request.method,
                    model=body.get("model") if body else None,
                    provider=auth.provider_type,
                    body=body,
                    body_bytes=None,
                    start_time=start_datetime,
                    status_code=status_code,
                    response_body={"stream": True},
                    request_headers=original_headers,
                    request_log_id=stream_log_id,  # Use pre-generated ID
                    first_token_time=None,  # Set in update_stream_response_async from first chunk time
                )
            )
            return StreamingResponse(
                stream_from_queue(),
                status_code=status_code,
                headers=resp_headers,
            )
        except httpx.TimeoutException:
            raise
        except Exception as e:
            logger.error("Proxy stream error: %s", e)
            return Response(
                content=json.dumps({"error": str(e)}),
                status_code=502,
                media_type="application/json",
            )

    # --- Non-streaming: read full response then return ---
    try:
        provider_response = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            json=body if body else None,
        )

        response_content = provider_response.content
        response_body_for_log: dict = {}
        try:
            if (provider_response.headers.get("content-type") or "").startswith("application/json"):
                response_body_for_log = json.loads(response_content)
                # Convert Anthropic/DashScope format to OpenAI format for consistent logging
                # Only convert for explicit Anthropic endpoints (URLs containing /anthropic path)
                is_anthropic_format = (
                    auth.provider_type in ("anthropic", "dashscope_anthropic") or
                    (auth.base_url and "/anthropic" in auth.base_url.lower())
                )
                if is_anthropic_format and (response_body_for_log.get("type") == "message" or isinstance(response_body_for_log.get("content"), list)):
                    response_body_for_log = _convert_anthropic_to_openai_format(response_body_for_log)
        except Exception:
            pass

        asyncio.create_task(
            record_response_async(
                proxy_key_id=auth.proxy_key_id,
                path=f"/v1/{path}",
                method=request.method,
                model=body.get("model") if body else None,
                provider=auth.provider_type,
                body=body,
                body_bytes=body_bytes,
                start_time=start_datetime,
                status_code=provider_response.status_code,
                response_body=response_body_for_log,
                request_headers=original_headers,
            )
        )

        return Response(
            content=response_content,
            status_code=provider_response.status_code,
            headers=dict(provider_response.headers),
        )

    except httpx.TimeoutException as e:
        # Only log timeout errors (fail-open for availability)
        logger.error(f"Request timeout: {e}")
        return Response(
            content=json.dumps({"error": "Request timeout"}),
            status_code=504,
            media_type="application/json"
        )
    except Exception as e:
        logger.error(f"Proxy error: {e}")
        return Response(
            content=json.dumps({"error": str(e)}),
            status_code=502,
            media_type="application/json"
        )
