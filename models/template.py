from __future__ import annotations

import enum

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base, TimestampMixin


class MatchMode(str, enum.Enum):
    """关键词匹配模式。"""

    EXACT = "exact"
    FUZZY = "fuzzy"


class Template(TimestampMixin, Base):
    """租户 Bot 的 Inline 模板。"""

    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant_bots.id"), index=True, nullable=False)
    keyword: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    match_mode: Mapped[str] = mapped_column(String(32), default=MatchMode.FUZZY.value)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    photo_url: Mapped[str | None] = mapped_column(Text)
    buttons_json: Mapped[list | None] = mapped_column(JSON)
    weight: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    tenant = relationship("TenantBot", back_populates="templates")
