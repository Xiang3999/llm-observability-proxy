"""LLM API Proxy routes - Optimized for minimal latency."""

import json
import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
import httpx
import structlog

from src.auth.middleware import get_proxy_auth, ProxyAuthResult
from src.recorder.recorder import RequestRecorder
from src.cache.semantic_cache import SemanticCache
from src.config import settings

router = APIRouter(tags=["Proxy"])

# Global semantic cache instance (initialized once)
_semantic_cache: Optional[SemanticCache] = None

# Global HTTP client with connection pooling for better performance
_http_client: Optional[httpx.AsyncClient] = None

logger = structlog.get_logger(__name__)


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
_STREAM_BODY_CHUNK_SIZE = 8192


async def _stream_body_chunks(body: dict):
    """Async generator: serialize body to JSON and yield in chunks. Use for upstream request so server sees chunked transfer like direct client."""
    data = json.dumps(body).encode("utf-8")
    for i in range(0, len(data), _STREAM_BODY_CHUNK_SIZE):
        yield data[i : i + _STREAM_BODY_CHUNK_SIZE]


# Provider base URLs
PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}


def _safe_body_for_db(obj: Optional[Dict[str, Any]]) -> dict:
    """Return a JSON-serializable copy for DB (request_body/response_body columns). Avoids serialization errors."""
    if obj is None:
        return {}
    try:
        return json.loads(json.dumps(obj, default=str))
    except (TypeError, ValueError):
        return {}


def _sum_detail_tokens(details: dict) -> Optional[int]:
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


def _parse_openai_stream_chunks(chunks: list[bytes]) -> dict:
    """Parse OpenAI-style SSE chunks into one response dict (choices[0].message.content + usage)."""
    if not chunks:
        return {"stream": True}
    try:
        raw = b"".join(chunks).decode("utf-8", errors="replace")
    except Exception:
        return {"stream": True}
    content_parts = []
    usage = {}
    response_id = None
    model = None
    # Split by double newline to get full SSE events (usage often in last event, may span chunk boundary)
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        for line in block.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                payload = line[6:].strip()
                if payload == "[DONE]":
                    continue
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                response_id = response_id or obj.get("id")
                model = model or obj.get("model")
                choices = obj.get("choices") or []
                if choices and isinstance(choices[0], dict):
                    delta = choices[0].get("delta") or {}
                    if isinstance(delta, dict) and "content" in delta and delta["content"]:
                        content_parts.append(delta["content"])
                # Debug: log any SSE event that has usage or cache-related keys (set LOG_LEVEL=DEBUG to see)
                if "usage" in obj or "prompt_tokens" in obj or "input_tokens" in obj or "cached_tokens" in str(obj) or "cache_creation" in str(obj):
                    logger.debug(
                        "stream_sse_usage_chunk",
                        raw_obj=obj,
                        has_usage="usage" in obj,
                        usage_keys=list(obj.get("usage", {}).keys()) if isinstance(obj.get("usage"), dict) else None,
                    )
                # Top-level usage (OpenAI / DashScope)
                if "usage" in obj and isinstance(obj["usage"], dict):
                    usage.update(_normalize_usage(obj["usage"]))
                # DashScope/Kimi: usage at top level as input_tokens / output_tokens
                if "prompt_tokens" in obj or "input_tokens" in obj or "output_tokens" in obj or "completion_tokens" in obj:
                    usage.update(_normalize_usage(obj))
                # Nested usage.usage_details (Bailian/DashScope)
                inner = (obj.get("usage") or {}) if isinstance(obj.get("usage"), dict) else {}
                if inner.get("usage_details") or inner.get("input_tokens") is not None or inner.get("output_tokens") is not None:
                    usage.update(_normalize_usage(inner))
    content = "".join(content_parts) if content_parts else ""
    usage_final = _normalize_usage(usage) if usage else {}
    logger.debug(
        "stream_reconstructed_usage",
        usage_final=usage_final,
        usage_raw_keys=list(usage.keys()) if usage else None,
    )
    if not usage_final:
        usage_final = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    return {
        "id": response_id,
        "model": model,
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": usage_final,
    }


async def create_stream_request_log_async(
    proxy_key_id: str,
    path: str,
    method: str,
    model: Optional[str],
    provider: str,
    body: Optional[Dict[str, Any]],
    start_time: datetime,
    status_code: int,
    request_headers: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
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
):
    """Update an existing stream request log with reconstructed response from chunks."""
    from src.models.database import AsyncSessionLocal
    from sqlalchemy import select
    from src.models.request_log import RequestLog

    response_body = _parse_openai_stream_chunks(chunks)
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
            logger.error("Update stream response failed: %s", e)


async def record_response_async(
    proxy_key_id: str,
    path: str,
    method: str,
    model: Optional[str],
    provider: str,
    body: Optional[Dict[str, Any]],
    body_bytes: Optional[bytes],
    start_time: datetime,
    status_code: int,
    response_body: dict,
    request_headers: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
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
            )
            end_time = datetime.now()
            await recorder.record_response(
                status_code=status_code,
                headers={},
                body=response_body,
                end_time=end_time,
                first_token_time=end_time,
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
    body: Optional[Dict[str, Any]] = None
    body_bytes: Optional[bytes] = None
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
    target_url = f"{base_url}/{path}"
    try:
        target_host = urlparse(target_url).netloc or target_url
    except Exception:
        target_host = "(parse error)"
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
    if auth.provider_type == "anthropic":
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
            stream_log_id_ref: Dict[str, Optional[str]] = {"id": None}

            upstream_start = time.perf_counter()

            # Ask upstream for usage in stream (e.g. DashScope needs stream_options.include_usage)
            body_with_usage = dict(body)
            if "stream_options" not in body_with_usage:
                body_with_usage["stream_options"] = {}
            if not isinstance(body_with_usage["stream_options"], dict):
                body_with_usage["stream_options"] = {}
            body_with_usage["stream_options"]["include_usage"] = True

            async def stream_worker() -> None:
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
                    await queue.put(("done",))
                    rid = stream_log_id_ref.get("id")
                    if rid and chunks_collector:
                        asyncio.create_task(
                            update_stream_response_async(rid, list(chunks_collector), datetime.now())
                        )

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
            except asyncio.TimeoutError:
                task.cancel()
                elapsed_ms = (time.perf_counter() - upstream_start) * 1000
                logger.error(
                    "stream timeout waiting for upstream headers",
                    path=path,
                    timeout_s=stream_timeout,
                    elapsed_ms=round(elapsed_ms),
                )
                raise httpx.TimeoutException("Stream timeout")
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
            # Always await recording so dashboard always gets a row (no fire-and-forget loss)
            stream_log_id = await record_response_async(
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
            )
            if stream_log_id:
                stream_log_id_ref["id"] = stream_log_id
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
