"""API routes for proxy key management."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.key_manager import KeyManager
from src.auth.middleware import verify_master_key
from src.models.database import get_db

router = APIRouter(prefix="/api/proxy-keys", tags=["Proxy Keys"])

# Type alias for database session dependency
DbSession = Annotated[AsyncSession, Depends(get_db)]


class ProxyKeyCreate(BaseModel):
    """Request body for creating a proxy key."""
    name: str
    provider_key_id: str


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_proxy_key(
    data: ProxyKeyCreate,
    db: DbSession,
    _: str = Depends(verify_master_key)
):
    """Create a new proxy key.

    Args:
        name: Name for the proxy key (e.g., app name)
        provider_key_id: ID of the provider key to link to
    """
    key_manager = KeyManager(db)

    # Verify provider key exists
    provider_key = await key_manager.get_provider_key(data.provider_key_id)
    if not provider_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider key not found"
        )

    # Create proxy key
    proxy_key, plain_key = await key_manager.create_proxy_key(
        name=data.name,
        provider_key_id=data.provider_key_id
    )

    return {
        "id": proxy_key.id,
        "name": proxy_key.name,
        "proxy_key": plain_key,  # Only shown once
        "provider_key_id": proxy_key.provider_key_id,
        "created_at": proxy_key.created_at.isoformat()
    }


@router.get("")
async def list_proxy_keys(
    db: DbSession,
    provider_key_id: str | None = None,
    _: str = Depends(verify_master_key)
):
    """List all proxy keys."""
    key_manager = KeyManager(db)
    proxy_keys = await key_manager.list_proxy_keys(provider_key_id)

    return [
        {
            "id": pk.id,
            "name": pk.name,
            "provider_key_id": pk.provider_key_id,
            "created_at": pk.created_at.isoformat(),
            "is_active": pk.is_active
        }
        for pk in proxy_keys
    ]


@router.get("/{key_id}")
async def get_proxy_key(
    key_id: str,
    db: DbSession,
    _: str = Depends(verify_master_key)
):
    """Get a specific proxy key."""
    key_manager = KeyManager(db)
    proxy_keys = await key_manager.list_proxy_keys()

    proxy_key = next((pk for pk in proxy_keys if pk.id == key_id), None)
    if not proxy_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proxy key not found"
        )

    # Get usage stats
    stats = await key_manager.get_usage_stats(key_id)

    return {
        "id": proxy_key.id,
        "name": proxy_key.name,
        "provider_key_id": proxy_key.provider_key_id,
        "created_at": proxy_key.created_at.isoformat(),
        "is_active": proxy_key.is_active,
        "usage": stats
    }


@router.delete("/{key_id}")
async def delete_proxy_key(
    key_id: str,
    db: DbSession,
    _: str = Depends(verify_master_key)
):
    """Delete (deactivate) a proxy key."""
    from src.auth.middleware import get_auth_cache
    from src.models.proxy_key import ProxyKey
    from sqlalchemy import select

    # Get proxy key first to invalidate cache
    result = await db.execute(select(ProxyKey).where(ProxyKey.id == key_id))
    proxy_key = result.scalar_one_or_none()

    if not proxy_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proxy key not found"
        )

    # Soft delete
    proxy_key.is_active = False
    await db.commit()

    # Invalidate auth cache for this proxy key
    get_auth_cache().invalidate_by_proxy_key_id(key_id)

    return {"message": "Proxy key deleted successfully"}


@router.get("/{key_id}/usage")
async def get_proxy_key_usage(
    key_id: str,
    db: DbSession,
    _: str = Depends(verify_master_key)
):
    """Get usage statistics for a proxy key."""
    key_manager = KeyManager(db)
    stats = await key_manager.get_usage_stats(key_id)

    return stats
