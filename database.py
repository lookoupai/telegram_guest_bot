from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy 声明式模型基类。"""


class TimestampMixin:
    """通用时间字段。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


settings = get_settings()
sqlite_file_path = settings.sqlite_file_path
if sqlite_file_path is not None:
    sqlite_file_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(settings.database_url, echo=False, future=True)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """提供自动提交/回滚的数据库会话。"""

    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """MVP 启动时自动建表；生产迁移仍保留 Alembic。"""

    import models  # noqa: F401 触发模型注册

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """关闭数据库连接池。"""

    await engine.dispose()
