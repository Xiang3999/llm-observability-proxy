"""Provider Key model - stores encrypted provider API keys."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String, Text, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.database import Base


class ProviderType(str, enum.Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    AZURE_OPENAI = "azure_openai"
    CUSTOM = "custom"


class ProviderKey(Base):
    """Provider API Key model."""

    __tablename__ = "provider_keys"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(SQLEnum(ProviderType), nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    supported_models: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationship to proxy keys
    proxy_keys: Mapped[list["ProxyKey"]] = relationship(  # noqa: F821
        back_populates="provider_key",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ProviderKey(id={self.id}, name={self.name}, provider={self.provider})>"
