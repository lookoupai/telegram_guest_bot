from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand

from config import Settings
from database import session_scope
from handlers.guest import tenant_guest_router
from handlers.inline import tenant_inline_router
from handlers.tenant_info import tenant_info_router
from handlers.tenant_manage import tenant_manage_router
from handlers.tenant_wizard import tenant_wizard_router
from services.tenant_service import get_active_tenants, set_tenant_error
from utils.crypto import TokenCipher

logger = logging.getLogger(__name__)


class TenantBotManager:
    """租户 Bot 生命周期管理器。

    MVP 使用 polling：每个租户 Bot 一个后台 polling task。
    后续 Docker/生产切 webhook 时，只需要替换这个类的启动/停止策略。
    """

    def __init__(self, settings: Settings, token_cipher: TokenCipher) -> None:
        self._settings = settings
        self._token_cipher = token_cipher
        self._tasks: dict[int, asyncio.Task] = {}
        self._manager_username: str | None = None

    def set_manager_username(self, username: str | None) -> None:
        """设置管理主 Bot 用户名，用于租户 Bot 提示文案。"""

        self._manager_username = username

    async def start_all(self) -> None:
        """启动数据库中所有启用的租户 Bot。"""

        async with session_scope() as session:
            tenants = await get_active_tenants(session)

        for tenant in tenants:
            await self.start_tenant_by_id(tenant.id)

    async def reload_all(self) -> None:
        """重载所有租户 Bot。"""

        await self.stop_all()
        await self.start_all()

    async def start_tenant_by_id(self, tenant_id: int) -> None:
        """按租户 ID 启动租户 Bot。"""

        if tenant_id in self._tasks and not self._tasks[tenant_id].done():
            return

        async with session_scope() as session:
            from models.tenant_bot import TenantBot

            tenant = await session.get(TenantBot, tenant_id)
            if tenant is None or not tenant.is_active:
                return

            token = self._token_cipher.decrypt(tenant.encrypted_token)
            username = tenant.username

        task = asyncio.create_task(
            self._run_tenant_polling(
                tenant_id=tenant_id,
                username=username,
                token=token,
            ),
            name=f"tenant-bot-{tenant_id}",
        )
        self._tasks[tenant_id] = task
        logger.info("已启动租户 Bot polling: tenant_id=%s username=@%s", tenant_id, username)

    async def stop_tenant(self, tenant_id: int) -> None:
        """停止单个租户 Bot。"""

        task = self._tasks.pop(tenant_id, None)
        if task is None or task.done():
            return

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info("已停止租户 Bot polling: tenant_id=%s", tenant_id)

    async def stop_all(self) -> None:
        """停止所有租户 Bot。"""

        tenant_ids = list(self._tasks)
        for tenant_id in tenant_ids:
            await self.stop_tenant(tenant_id)

    async def _run_tenant_polling(self, tenant_id: int, username: str, token: str) -> None:
        """租户 Bot polling 主循环。"""

        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dispatcher = Dispatcher()
        dispatcher.include_router(tenant_guest_router)
        dispatcher.include_router(tenant_inline_router)
        dispatcher.include_router(tenant_wizard_router)
        dispatcher.include_router(tenant_manage_router)
        dispatcher.include_router(tenant_info_router)

        try:
            if self._settings.delete_webhook_on_start:
                await bot.delete_webhook(drop_pending_updates=True)

            me = await bot.get_me()
            await bot.set_my_commands(
                [
                    BotCommand(command="start", description="打开管理菜单"),
                    BotCommand(command="seedtemplates", description="写入测试模板"),
                    BotCommand(command="newtemplate", description="分步新增模板"),
                    BotCommand(command="addtemplate", description="添加模板"),
                    BotCommand(command="mytemplates", description="查看模板"),
                    BotCommand(command="test", description="测试关键词"),
                    BotCommand(command="status", description="查看 Guest 状态"),
                    BotCommand(command="edittemplate", description="编辑模板"),
                    BotCommand(command="deltemplate", description="删除模板"),
                    BotCommand(command="setdefault", description="设置默认模板"),
                ]
            )
            async with session_scope() as session:
                from models.tenant_bot import TenantBot

                tenant = await session.get(TenantBot, tenant_id)
                if tenant is not None:
                    tenant.supports_guest_queries = me.supports_guest_queries
                    tenant.supports_inline_queries = me.supports_inline_queries
                    tenant.last_error = None

            logger.info(
                "租户 Bot 运行中: tenant_id=%s username=@%s guest=%s inline=%s",
                tenant_id,
                me.username,
                me.supports_guest_queries,
                me.supports_inline_queries,
            )

            await dispatcher.start_polling(
                bot,
                allowed_updates=["guest_message", "message", "callback_query"],
                handle_signals=False,
                close_bot_session=True,
                manager_username=self._manager_username,
                tenant_username=me.username,
                settings=self._settings,
            )
        except asyncio.CancelledError:
            raise
        except TelegramAPIError as exc:
            logger.exception("租户 Bot Telegram API 错误: tenant_id=%s username=@%s", tenant_id, username)
            async with session_scope() as session:
                await set_tenant_error(session, tenant_id, str(exc))
        except Exception as exc:
            logger.exception("租户 Bot 运行异常: tenant_id=%s username=@%s", tenant_id, username)
            async with session_scope() as session:
                await set_tenant_error(session, tenant_id, str(exc))
        finally:
            await bot.session.close()
            self._tasks.pop(tenant_id, None)
