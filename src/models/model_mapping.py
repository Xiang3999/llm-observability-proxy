"""Model mapping - maps request model names to actual model names."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.database import Base


class ModelMapping(Base):
    """Model mapping for translating model names.

    Example: glm-5 -> claude-sonnet-4-6
    """

    __tablename__ = "model_mappings"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    # Source model name (what client sends)
    source_model: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # Target model name (what to send to provider)
    target_model: Mapped[str] = mapped_column(String(255), nullable=False)
    # Optional description
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Active status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<ModelMapping({self.source_model} -> {self.target_model})>"