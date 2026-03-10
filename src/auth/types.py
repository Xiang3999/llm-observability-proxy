"""Auth-related types to avoid circular imports."""

from types import SimpleNamespace
from typing import Any, Optional


class ProxyAuthResult:
    """Result of proxy key authentication."""

    def __init__(
        self,
        proxy_key: Any,  # ProxyKey OR SimpleNamespace with .id, .name
        provider_key: str,
        provider_type: str,
        base_url: Optional[str] = None,
    ):
        self.proxy_key = proxy_key
        self.provider_key = provider_key
        self.provider_type = provider_type
        self.base_url = base_url
        self.proxy_key_id = proxy_key.id
        self.app_name = proxy_key.name


def make_cached_auth_result(
    provider_key: str,
    provider_type: str,
    base_url: Optional[str],
    proxy_key_id: str,
    app_name: str,
) -> ProxyAuthResult:
    """Build ProxyAuthResult without ORM (for cache hit)."""
    proxy_key = SimpleNamespace(id=proxy_key_id, name=app_name)
    return ProxyAuthResult(
        proxy_key=proxy_key,
        provider_key=provider_key,
        provider_type=provider_type,
        base_url=base_url,
    )
