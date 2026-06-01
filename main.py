from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from bot import TenantBotManager
from config import ConfigError, get_settings
from database import close_db, init_db
from handlers import admin_router, manage_router
from utils.crypto import TokenCipher
from utils.logging import setup_logging

if sys.version_info < (3, 10):
    raise RuntimeError("本项目需要 Python 3.10 或更高版本。")


logger = logging.getLogger(__name__)


async def main() -> None:
    """应用入口。

    启动一个管理主 Bot，同时按数据库中的租户配置启动多个租户 Bot polling task。
    """

    settings = get_settings()
    setup_logging(settings.log_level)

    token_cipher = TokenCipher(settings.fernet_key)
    await init_db()

    master_bot = Bot(
        token=settings.master_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(manage_router)
    dispatcher.include_router(admin_router)

    tenant_manager = TenantBotManager(settings=settings, token_cipher=token_cipher)

    try:
        if settings.delete_webhook_on_start:
            await master_bot.delete_webhook(drop_pending_updates=True)

        me = await master_bot.get_me()
        await master_bot.set_my_commands(
            [
                BotCommand(command="start", description="打开管理菜单"),
                BotCommand(command="createbot", description="创建受管理 Bot"),
                BotCommand(command="mybots", description="查看我的 Bot"),
                BotCommand(command="tenantstatus", description="查看租户状态"),
                BotCommand(command="refreshbot", description="刷新 Guest 状态"),
                BotCommand(command="seedtemplates", description="写入测试模板"),
                BotCommand(command="addtemplate", description="添加模板"),
                BotCommand(command="mytemplates", description="查看模板"),
            ]
        )
        logger.info(
            "管理主 Bot 已启动: @%s can_manage_bots=%s supports_inline_queries=%s",
            me.username,
            me.can_manage_bots,
            me.supports_inline_queries,
        )
        if me.can_manage_bots is not True:
            logger.warning("主 Bot 尚未开启 can_manage_bots，/createbot 将不可用。")

        tenant_manager.set_manager_username(me.username)
        await tenant_manager.start_all()
        await dispatcher.start_polling(
            master_bot,
            allowed_updates=["message", "callback_query", "managed_bot"],
            settings=settings,
            token_cipher=token_cipher,
            tenant_manager=tenant_manager,
        )
    finally:
        await tenant_manager.stop_all()
        await master_bot.session.close()
        await close_db()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
