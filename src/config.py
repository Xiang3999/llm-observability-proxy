"""Application configuration."""

from typing import Literal, Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    # Master API Key for admin operations
    master_api_key: str = "change-me-in-production"

    # Database (use aiosqlite for async support)
    database_url: str = "sqlite+aiosqlite:///./data/proxy.db"

    # Server (127.0.0.1 = local only; 0.0.0.0 = allow remote)
    host: str = "127.0.0.1"
    port: int = 8000

    # Logging
    log_level: str = "INFO"

    # Storage backend for request/response bodies
    storage_type: Literal["sqlite", "s3"] = "sqlite"

    # S3 configuration (if storage_type is s3)
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    # Semantic Cache (disabled by default)
    cache_enabled: bool = False
    cache_similarity_threshold: float = 0.95  # 0.0 - 1.0, higher = more strict
    cache_ttl_seconds: int = 3600  # 1 hour default
    cache_max_size: int = 10000  # max cached entries

    # Auth cache: avoid DB hit on every request
    auth_cache_ttl_seconds: int = 300  # 5 min
    auth_cache_max_size: int = 10_000

    # 连接预热：启动时对以下 URL 发一次请求，把 TCP+TLS 建好放进连接池，降低首包延迟
    # 逗号分隔，如: https://coding.dashscope.aliyuncs.com/v1
    prewarm_urls: str = ""

    # 上游请求超时（秒）。客户端（如 OpenClaw）单次 LLM 请求超时可能较短，若上游较慢可适当调大
    upstream_timeout_seconds: float = 120.0

    # =====================================================================
    # UI Pagination and Filtering Defaults
    # =====================================================================

    # Default pagination size for request lists
    default_per_page: int = 50

    # Default time range (days) for analytics and filtering
    default_days: int = 7

    # Default limit for request analysis
    default_limit: int = 100

    # Available time range options (days)
    days_options: list = [1, 3, 7, 30, 90, 0]  # 0 = All time

    # Available limit options
    limit_options: list = [100, 500, 1000, 5000]

    # Maximum limit for analysis (performance protection)
    max_analysis_limit: int = 10000

    # System prompts page size
    system_prompts_per_page: int = 50

    # =====================================================================
    # Database Maintenance (SQLite)
    # =====================================================================

    # WAL checkpoint interval in seconds (default: 5 minutes)
    db_checkpoint_interval_seconds: int = 300

    # Backup interval in hours (default: 24 hours)
    db_backup_interval_hours: int = 24

    # Number of backup files to keep (default: 7)
    db_backup_keep_count: int = 7

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
