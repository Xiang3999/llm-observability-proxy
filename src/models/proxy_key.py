"""Proxy Key model - maps proxy keys to provider keys."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.database import Base
from src.models.page_view import PageView  # noqa: F401 - required for relationship


class ProxyKey(Base):
    """Proxy API Key model - used by client applications."""

    __tablename__ = "proxy_keys"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    proxy_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    proxy_key_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    provider_key_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("provider_keys.id", ondelete="CASCADE"),
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationship
    provider_key: Mapped["ProviderKey"] = relationship(  # noqa: F821
        back_populates="proxy_keys"
    )

    # Relationship to requests
    requests: Mapped[list["RequestLog"]] = relationship(  # noqa: F821
        back_populates="proxy_key",
        cascade="all, delete-orphan"
    )

    # Relationship to page views
    page_views: Mapped[list["PageView"]] = relationship(  # noqa: F821
        back_populates="proxy_key",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ProxyKey(id={self.id}, name={self.name})>"
