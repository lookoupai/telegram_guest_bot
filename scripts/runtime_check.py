from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from aiogram import Bot
from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_settings
from database import close_db, init_db, session_scope
from models.template import Template
from models.tenant_bot import TenantBot
from models.user import User
from utils.crypto import TokenCipher


async def check_database() -> list[TenantBot]:
    """检查数据库基础状态，不输出任何 token。"""

    async with session_scope() as session:
        user_count = await session.scalar(select(func.count(User.id)))
        tenant_count = await session.scalar(select(func.count(TenantBot.id)))
        template_count = await session.scalar(select(func.count(Template.id)))
        result = await session.execute(select(TenantBot).order_by(TenantBot.created_at.desc()))
        tenants = list(result.scalars().all())

    print(f"database_ok users={user_count or 0} tenants={tenant_count or 0} templates={template_count or 0}")
    for tenant in tenants:
        print(
            f"tenant id={tenant.id} @{tenant.username} "
            f"active={tenant.is_active} guest={tenant.supports_guest_queries} "
            f"managed={tenant.is_managed} source={tenant.token_source}"
        )
    return tenants


async def check_telegram(tenants: list[TenantBot]) -> None:
    """调用 Telegram getMe 检查主 Bot 和租户 Bot 能力，不打印 token。"""

    settings = get_settings()
    cipher = TokenCipher(settings.fernet_key)

    master_bot = Bot(token=settings.master_bot_token)
    try:
        master = await master_bot.get_me()
        print(
            f"master_ok @{master.username} "
            f"can_manage_bots={master.can_manage_bots} guest={master.supports_guest_queries}"
        )
    finally:
        await master_bot.session.close()

    for tenant in tenants:
        raw_token = cipher.decrypt(tenant.encrypted_token)
        tenant_bot = Bot(token=raw_token)
        try:
            me = await tenant_bot.get_me()
            print(
                f"tenant_api_ok id={tenant.id} @{me.username} "
                f"guest={me.supports_guest_queries} inline={me.supports_inline_queries}"
            )
        finally:
            await tenant_bot.session.close()


async def main() -> None:
    """运行部署前/部署后检查。"""

    parser = argparse.ArgumentParser(description="Guest Bot runtime checker")
    parser.add_argument("--telegram", action="store_true", help="调用 Telegram getMe 检查 Bot 能力")
    args = parser.parse_args()

    await init_db()
    try:
        tenants = await check_database()
        if args.telegram:
            await check_telegram(tenants)
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
