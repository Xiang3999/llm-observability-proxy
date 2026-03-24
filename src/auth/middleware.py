"""Authentication middleware and dependencies."""

import time
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.auth_cache import AuthCache
from src.auth.key_manager import KeyManager
from src.auth.types import ProxyAuthResult, make_cached_auth_result
from src.config import settings
from src.models.database import get_db

logger = structlog.get_logger(__name__)

# In-memory auth cache to avoid DB hit on every request
_auth_cache: AuthCache | None = None


def get_auth_cache() -> AuthCache:
    return _get_auth_cache()


# Type alias for database session dependency
DbSession = Annotated[AsyncSession, Depends(get_db)]


# HTTP Bearer token security
security = HTTPBearer(auto_error=False)


def _get_auth_cache() -> AuthCache:
    global _auth_cache
    if _auth_cache is None:
        _auth_cache = AuthCache(
            ttl_seconds=settings.auth_cache_ttl_seconds,
            max_size=settings.auth_cache_max_size,
        )
    return _auth_cache


async def verify_master_key(
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> str:
    """Verify the master API key for admin operations."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials"
        )

    if credentials.credentials != settings.master_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

    return credentials.credentials


async def verify_proxy_key(
    db: DbSession,
    bearer_token: str
) -> ProxyAuthResult:
    """Verify a proxy key and return auth result.

    Uses in-memory cache first to avoid DB round-trip on hot path.
    """
    cache = _get_auth_cache()
    cached = cache.get(bearer_token)
    if cached is not None:
        logger.debug("auth cache hit", proxy_key_id=getattr(cached, "proxy_key_id", None))
        return cached

    t0 = time.perf_counter()
    key_manager = KeyManager(db)
    result = await key_manager.get_proxy_key_with_provider(bearer_token)
    db_ms = (time.perf_counter() - t0) * 1000
    logger.info("auth cache miss", db_lookup_ms=round(db_ms), found=result is not None)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid proxy key"
        )

    proxy_key, provider_key = result
    provider_key_value = provider_key.encrypted_key

    # Store cacheable copy (no ORM) so we don't hold DB session refs
    to_cache = make_cached_auth_result(
        provider_key=provider_key_value,
        provider_type=provider_key.provider.value,
        base_url=provider_key.base_url,
        proxy_key_id=proxy_key.id,
        app_name=proxy_key.name,
    )
    cache.set(bearer_token, to_cache)
    return ProxyAuthResult(
        proxy_key=proxy_key,
        provider_key=provider_key_value,
        provider_type=provider_key.provider.value,
        base_url=provider_key.base_url,
    )


async def get_proxy_auth(
    db: DbSession,
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> ProxyAuthResult:
    """Get proxy authentication from request."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials"
        )

    # Extract the key (remove 'Bearer ' prefix if present)
    token = credentials.credentials
    if token.startswith("Bearer "):
        token = token[7:]

    return await verify_proxy_key(db, token)
