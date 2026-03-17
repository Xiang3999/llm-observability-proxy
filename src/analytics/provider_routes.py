"""API routes for provider key management."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.key_manager import KeyManager
from src.auth.middleware import verify_master_key
from src.models.database import get_db
from src.models.provider_key import ProviderKey, ProviderType

router = APIRouter(prefix="/api/provider-keys", tags=["Provider Keys"])

# Type alias for database session dependency
DbSession = Annotated[AsyncSession, Depends(get_db)]


class ProviderKeyCreate(BaseModel):
    """Request body for creating a provider key."""
    name: str
    provider: str
    api_key: str
    base_url: str | None = None
    supported_models: list[str] | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_provider_key(
    data: ProviderKeyCreate,
    db: DbSession,
    _: str = Depends(verify_master_key)
):
    """Create a new provider key.

    Args:
        name: Name for the provider key
        provider: Provider type (openai, anthropic, gemini, etc.)
        api_key: The actual API key from the provider
    """
    key_manager = KeyManager(db)

    try:
        provider_type = ProviderType(data.provider.lower())
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid provider. Must be one of: {[p.value for p in ProviderType]}"
        ) from err

    provider_key = await key_manager.create_provider_key(
        name=data.name,
        provider=provider_type,
        api_key=data.api_key,
        base_url=data.base_url,
        supported_models=data.supported_models
    )

    return {
        "id": provider_key.id,
        "name": provider_key.name,
        "provider": provider_key.provider.value,
        "created_at": provider_key.created_at.isoformat(),
        # Never return the actual key
    }


@router.get("")
async def list_provider_keys(
    db: DbSession,
    _: str = Depends(verify_master_key)
):
    """List all provider keys (without exposing the actual keys)."""
    key_manager = KeyManager(db)

    # Get unique provider keys
    result = await key_manager.db.execute(
        select(ProviderKey).where(ProviderKey.is_active)
    )
    provider_keys = list(result.scalars().all())

    return [
        {
            "id": pk.id,
            "name": pk.name,
            "provider": pk.provider.value,
            "base_url": pk.base_url,
            "supported_models": pk.supported_models,
            "created_at": pk.created_at.isoformat(),
            # Never return the actual key
        }
        for pk in provider_keys
    ]


@router.delete("/{key_id}")
async def delete_provider_key(
    key_id: str,
    db: DbSession,
    _: str = Depends(verify_master_key)
):
    """Delete a provider key (will also deactivate linked proxy keys)."""
    from src.auth.middleware import get_auth_cache

    key_manager = KeyManager(db)
    provider_key = await key_manager.get_provider_key(key_id)

    if not provider_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider key not found"
        )

    provider_key.is_active = False
    await db.commit()

    # Invalidate auth cache for this provider key
    get_auth_cache().invalidate_by_provider_key_id(key_id)

    return {"message": "Provider key deleted successfully"}


class ProviderKeyUpdate(BaseModel):
    """Request body for updating a provider key."""
    name: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    supported_models: list[str] | None = None


@router.patch("/{key_id}")
async def update_provider_key(
    key_id: str,
    data: ProviderKeyUpdate,
    db: DbSession,
    _: str = Depends(verify_master_key)
):
    """Update a provider key's configuration."""
    from src.auth.middleware import get_auth_cache

    key_manager = KeyManager(db)
    provider_key = await key_manager.get_provider_key(key_id)

    if not provider_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider key not found"
        )

    # Update fields if provided
    if data.name is not None:
        provider_key.name = data.name
    if data.api_key is not None:
        provider_key.encrypted_key = data.api_key
    if data.base_url is not None:
        provider_key.base_url = data.base_url
    if data.supported_models is not None:
        provider_key.supported_models = data.supported_models

    await db.commit()

    # Invalidate auth cache for this provider key
    get_auth_cache().invalidate_by_provider_key_id(key_id)

    return {
        "id": provider_key.id,
        "name": provider_key.name,
        "base_url": provider_key.base_url,
        "supported_models": provider_key.supported_models,
    }
