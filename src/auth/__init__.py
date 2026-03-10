"""Authentication module."""

from src.auth.key_manager import KeyManager, generate_proxy_key, hash_key, verify_key
from src.auth.middleware import (
    verify_master_key,
    verify_proxy_key,
    get_proxy_auth,
    ProxyAuthResult,
    security
)

__all__ = [
    "KeyManager",
    "generate_proxy_key",
    "hash_key",
    "verify_key",
    "verify_master_key",
    "verify_proxy_key",
    "get_proxy_auth",
    "ProxyAuthResult",
    "security",
]
