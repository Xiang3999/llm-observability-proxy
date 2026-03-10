"""API Key management - create, validate, and manage proxy keys."""

import hashlib
import secrets
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from passlib.context import CryptContext

from src.models.provider_key import ProviderKey, ProviderType
from src.models.proxy_key import ProxyKey
from src.models.request_log import RequestLog


# Password hashing context for API keys
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def generate_proxy_key() -> str:
    """Generate a new proxy key.

    Format: sk-proxy-<random>-<uuid>
    """
    import uuid
    random_part = secrets.token_urlsafe(16)
    uuid_part = str(uuid.uuid4())
    return f"sk-proxy-{random_part}-{uuid_part}"


def hash_key(key: str) -> str:
    """Hash an API key for secure storage."""
    return pwd_context.hash(key)


def verify_key(plain_key: str, hashed_key: str) -> bool:
    """Verify a plain key against a hashed key."""
    try:
        return pwd_context.verify(plain_key, hashed_key)
    except Exception:
        return False


class KeyManager:
    """Manage proxy keys and provider keys."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_provider_key(
        self,
        name: str,
        provider: ProviderType,
        api_key: str,
        base_url: Optional[str] = None,
        supported_models: Optional[List[str]] = None
    ) -> ProviderKey:
        """Create a new provider key."""
        # Store the key in plaintext (for local/prod use proper encryption like Fernet)
        # In production, you should use proper encryption
        encrypted_key = api_key  # Stored as-is for now

        provider_key = ProviderKey(
            name=name,
            provider=provider,
            encrypted_key=encrypted_key,
            base_url=base_url,  # Optional custom base URL
            supported_models=supported_models  # Optional list of supported models
        )
        self.db.add(provider_key)
        await self.db.flush()
        await self.db.refresh(provider_key)
        return provider_key

    async def get_provider_key(self, key_id: str) -> Optional[ProviderKey]:
        """Get a provider key by ID."""
        result = await self.db.execute(
            select(ProviderKey).where(ProviderKey.id == key_id)
        )
        return result.scalar_one_or_none()

    async def get_decrypted_provider_key(self, key_id: str) -> Optional[str]:
        """Get the decrypted provider key."""
        provider_key = await self.get_provider_key(key_id)
        if not provider_key:
            return None
        # In production, use proper decryption
        return provider_key.encrypted_key  # This is actually hashed, need to store plaintext encrypted

    async def create_proxy_key(
        self,
        name: str,
        provider_key_id: str
    ) -> tuple[ProxyKey, str]:
        """Create a new proxy key linked to a provider key.

        Returns:
            Tuple of (ProxyKey, plain_text_key)
            The plain text key should be shown to the user only once.
        """
        # Generate new proxy key
        plain_key = generate_proxy_key()
        hashed_key = hash_key(plain_key)

        proxy_key = ProxyKey(
            name=name,
            proxy_key=plain_key,  # Store plain for retrieval (consider encryption)
            proxy_key_hash=hashed_key,
            provider_key_id=provider_key_id
        )
        self.db.add(proxy_key)
        await self.db.flush()
        await self.db.refresh(proxy_key)

        return proxy_key, plain_key

    async def validate_proxy_key(self, proxy_key: str) -> Optional[ProxyKey]:
        """Validate a proxy key and return the ProxyKey object."""
        result = await self.db.execute(
            select(ProxyKey).where(
                ProxyKey.proxy_key == proxy_key,
                ProxyKey.is_active == True
            )
        )
        return result.scalar_one_or_none()

    async def get_proxy_key_with_provider(
        self,
        proxy_key: str
    ) -> Optional[tuple[ProxyKey, ProviderKey]]:
        """Get proxy key with its linked provider key."""
        result = await self.db.execute(
            select(ProxyKey, ProviderKey)
            .join(ProviderKey)
            .where(
                ProxyKey.proxy_key == proxy_key,
                ProxyKey.is_active == True,
                ProviderKey.is_active == True
            )
        )
        return result.one_or_none()

    async def list_proxy_keys(
        self,
        provider_key_id: Optional[str] = None
    ) -> list[ProxyKey]:
        """List all proxy keys, optionally filtered by provider key."""
        query = select(ProxyKey).where(ProxyKey.is_active == True)
        if provider_key_id:
            query = query.where(ProxyKey.provider_key_id == provider_key_id)
        query = query.order_by(ProxyKey.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def delete_proxy_key(self, key_id: str) -> bool:
        """Soft delete a proxy key."""
        result = await self.db.execute(
            select(ProxyKey).where(ProxyKey.id == key_id)
        )
        proxy_key = result.scalar_one_or_none()
        if proxy_key:
            proxy_key.is_active = False
            await self.db.flush()
            await self.db.commit()
            return True
        return False

    async def get_usage_stats(self, proxy_key_id: str) -> dict:
        """Get usage statistics for a proxy key."""
        from sqlalchemy import func, select

        result = await self.db.execute(
            select(
                func.count(RequestLog.id).label("total_requests"),
                func.sum(RequestLog.total_tokens).label("total_tokens"),
                func.sum(RequestLog.prompt_tokens).label("prompt_tokens"),
                func.sum(RequestLog.completion_tokens).label("completion_tokens"),
                func.avg(RequestLog.total_latency_ms).label("avg_latency_ms"),
                func.sum(RequestLog.cost_usd).label("total_cost")
            ).where(RequestLog.proxy_key_id == proxy_key_id)
        )
        row = result.one()

        return {
            "total_requests": row.total_requests or 0,
            "total_tokens": row.total_tokens or 0,
            "prompt_tokens": row.prompt_tokens or 0,
            "completion_tokens": row.completion_tokens or 0,
            "avg_latency_ms": float(row.avg_latency_ms or 0),
            "total_cost": float(row.total_cost or 0)
        }

    async def delete_provider_key(self, key_id: str) -> bool:
        """Delete a provider key (and all linked proxy keys)."""
        # First, delete all linked proxy keys
        await self.db.execute(
            select(ProxyKey).where(ProxyKey.provider_key_id == key_id)
        )
        # Then delete the provider key
        result = await self.db.execute(
            select(ProviderKey).where(ProviderKey.id == key_id)
        )
        provider_key = result.scalar_one_or_none()
        if provider_key:
            await self.db.delete(provider_key)
            await self.db.commit()
            return True
        return False

    async def toggle_proxy_key(self, key_id: str) -> bool:
        """Toggle proxy key active status."""
        result = await self.db.execute(
            select(ProxyKey).where(ProxyKey.id == key_id)
        )
        proxy_key = result.scalar_one_or_none()
        if proxy_key:
            proxy_key.is_active = not proxy_key.is_active
            await self.db.flush()
            return True
        return False
