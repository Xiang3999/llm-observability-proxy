"""Request Log model - stores API request/response records."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    String, Integer, Boolean, DateTime, ForeignKey, Text,
    Numeric, JSON, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import func

from src.models.database import Base


class RequestLog(Base):
    """API Request Log model."""

    __tablename__ = "request_logs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    # Foreign key to proxy key
    proxy_key_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("proxy_keys.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Request details
    request_path: Mapped[str] = mapped_column(String(500), nullable=True)
    method: Mapped[str] = mapped_column(String(10), default="POST")
    model: Mapped[str] = mapped_column(String(100), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=True)

    # Response details
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Token usage
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Latency metrics (in milliseconds)
    total_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    time_to_first_token_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Timing
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Body storage paths (for large bodies stored externally)
    request_body_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    response_body_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Inline body storage (for small bodies)
    request_body: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    response_body: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Cost calculation
    cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 6), nullable=True)

    # Metadata
    user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    properties: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Request and Response Headers (for advanced analysis)
    request_headers: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    response_headers: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Anthropic-specific cache metrics
    cache_read_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cache_creation_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Anthropic billing/header info
    anthropic_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # Includes: cch (cache checksum), cc_version, cc_entrypoint, etc.

    # Usage breakdown
    usage_breakdown: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # Includes: input_tokens, output_tokens, cache_read_input_tokens, etc.

    # Relationship
    proxy_key: Mapped["ProxyKey"] = relationship(  # noqa: F821
        back_populates="requests"
    )

    # Indexes for common queries
    __table_args__ = (
        Index("idx_request_logs_created_at", "created_at"),
        Index("idx_request_logs_model", "model"),
        Index("idx_request_logs_status", "status_code"),
    )

    def __repr__(self) -> str:
        return f"<RequestLog(id={self.id}, model={self.model}, status={self.status_code})>"
