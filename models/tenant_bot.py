from __future__ import annotations

import enum

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base, TimestampMixin


class TokenSource(str, enum.Enum):
    """租户 Bot Token 来源。"""

    MANUAL = "manual"
    MANAGED = "managed"


class TenantBot(TimestampMixin, Base):
    """租户绑定的 Bot。每个 Bot 负责自己的 Inline Query。"""

    __tablename__ = "tenant_bots"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    bot_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(255))
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_source: Mapped[str] = mapped_column(String(32), default=TokenSource.MANUAL.value)
    is_managed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supports_inline_queries: Mapped[bool | None] = mapped_column(Boolean)
    supports_guest_queries: Mapped[bool | None] = mapped_column(Boolean)
    last_error: Mapped[str | None] = mapped_column(Text)

    owner = relationship("User", back_populates="tenant_bots")
    templates = relationship("Template", back_populates="tenant", cascade="all, delete-orphan")
