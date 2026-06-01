from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base, TimestampMixin


class User(TimestampMixin, Base):
    """使用管理 Bot 的 Telegram 用户。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    tenant_bots = relationship("TenantBot", back_populates="owner", cascade="all, delete-orphan")
