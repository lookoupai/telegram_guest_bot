from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import User as TelegramUser
from aiogram.utils.token import TokenValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from models.tenant_bot import TenantBot, TokenSource
from models.user import User
from utils.crypto import TokenCipher

logger = logging.getLogger(__name__)


class TenantTokenError(RuntimeError):
    """租户 Bot Token 校验失败。"""


async def ensure_user(
    session: AsyncSession,
    telegram_user: TelegramUser,
    settings: Settings,
) -> User:
    """创建或更新管理后台用户。"""

    result = await session.execute(select(User).where(User.telegram_id == telegram_user.id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            telegram_id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            is_admin=telegram_user.id in settings.admin_ids,
        )
        session.add(user)
        await session.flush()
        return user

    user.username = telegram_user.username
    user.first_name = telegram_user.first_name
    user.is_admin = telegram_user.id in settings.admin_ids
    return user


async def validate_bot_token(token: str) -> TelegramUser:
    """调用 getMe 校验 Bot Token，并返回 Bot 用户信息。"""

    try:
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    except TokenValidationError as exc:
        raise TenantTokenError(f"Token 格式错误：{exc}") from exc

    try:
        me = await bot.get_me()
    except TelegramAPIError as exc:
        raise TenantTokenError(f"Token 校验失败：{exc}") from exc
    finally:
        await bot.session.close()

    if not me.is_bot:
        raise TenantTokenError("Token 对应账号不是 Bot。")
    if not me.username:
        raise TenantTokenError("Bot 没有 username，无法作为 Inline Bot 使用。")
    return me


async def upsert_tenant_bot(
    session: AsyncSession,
    owner: User,
    bot_user: TelegramUser,
    raw_token: str,
    cipher: TokenCipher,
    token_source: TokenSource,
) -> TenantBot:
    """新增或更新租户 Bot。"""

    result = await session.execute(select(TenantBot).where(TenantBot.bot_user_id == bot_user.id))
    tenant = result.scalar_one_or_none()
    encrypted_token = cipher.encrypt(raw_token)
    normalized_username = (bot_user.username or str(bot_user.id)).lower()

    if tenant is None:
        tenant = TenantBot(
            owner_user_id=owner.id,
            bot_user_id=bot_user.id,
            username=normalized_username,
            first_name=bot_user.first_name,
            encrypted_token=encrypted_token,
            token_source=token_source.value,
            is_managed=token_source == TokenSource.MANAGED,
            is_active=True,
            supports_inline_queries=bot_user.supports_inline_queries,
            supports_guest_queries=bot_user.supports_guest_queries,
            last_error=None,
        )
        session.add(tenant)
        await session.flush()
        return tenant

    tenant.owner_user_id = owner.id
    tenant.username = normalized_username
    tenant.first_name = bot_user.first_name
    tenant.encrypted_token = encrypted_token
    tenant.token_source = token_source.value
    tenant.is_managed = token_source == TokenSource.MANAGED
    tenant.is_active = True
    tenant.supports_inline_queries = bot_user.supports_inline_queries
    tenant.supports_guest_queries = bot_user.supports_guest_queries
    tenant.last_error = None
    return tenant


async def get_active_tenants(session: AsyncSession) -> list[TenantBot]:
    """获取所有启用的租户 Bot。"""

    result = await session.execute(select(TenantBot).where(TenantBot.is_active.is_(True)))
    return list(result.scalars().all())


async def get_tenant_by_bot_id(session: AsyncSession, bot_user_id: int) -> TenantBot | None:
    """按 Bot ID 查询租户。"""

    result = await session.execute(select(TenantBot).where(TenantBot.bot_user_id == bot_user_id))
    return result.scalar_one_or_none()


async def get_tenant_by_username(
    session: AsyncSession,
    owner_user_id: int,
    username: str,
) -> TenantBot | None:
    """按用户名查询当前用户的租户 Bot。"""

    normalized_username = username.removeprefix("@").lower()
    result = await session.execute(
        select(TenantBot).where(
            TenantBot.owner_user_id == owner_user_id,
            TenantBot.username == normalized_username,
        )
    )
    return result.scalar_one_or_none()


async def list_owner_tenants(session: AsyncSession, owner_user_id: int) -> list[TenantBot]:
    """列出用户绑定的所有租户 Bot。"""

    result = await session.execute(
        select(TenantBot)
        .where(TenantBot.owner_user_id == owner_user_id)
        .order_by(TenantBot.created_at.desc())
    )
    return list(result.scalars().all())


async def set_tenant_error(
    session: AsyncSession,
    tenant_id: int,
    error_message: str,
) -> None:
    """记录租户运行错误并停用。"""

    tenant = await session.get(TenantBot, tenant_id)
    if tenant is None:
        return
    tenant.is_active = False
    tenant.last_error = error_message[:2000]
