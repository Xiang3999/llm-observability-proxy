"""Page view tracking model."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from src.models.database import Base


class PageView(Base):
    """Page view tracking model for analytics."""

    __tablename__ = "page_views"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Page information
    path = Column(String(500), nullable=False, index=True)
    page_name = Column(String(100), nullable=True)

    # Visitor information
    ip_address = Column(String(45), nullable=True)  # IPv6 max length
    user_agent = Column(Text, nullable=True)

    # Request information
    referer = Column(String(500), nullable=True)
    method = Column(String(10), nullable=True, default="GET")

    # Timing
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Optional: link to proxy key if authenticated
    proxy_key_id = Column(String(36), ForeignKey("proxy_keys.id"), nullable=True)
    proxy_key = relationship("ProxyKey", back_populates="page_views")


# Add relationship to ProxyKey model (will be imported in proxy_key.py)
