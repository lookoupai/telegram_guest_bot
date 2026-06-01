from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from config import Settings
from database import session_scope
from models.tenant_bot import TenantBot

admin_router = Router(name="admin")


def is_admin(message: Message, settings: Settings) -> bool:
    """判断消息发送者是否为管理员。"""

    return bool(message.from_user and message.from_user.id in settings.admin_ids)


@admin_router.message(Command("admin_tenants"))
async def admin_tenants_command(message: Message, settings: Settings) -> None:
    """管理员查看所有租户。"""

    if not is_admin(message, settings):
        await message.answer("无权限。")
        return

    async with session_scope() as session:
        result = await session.execute(select(TenantBot).order_by(TenantBot.created_at.desc()))
        tenants = list(result.scalars().all())

    if not tenants:
        await message.answer("暂无租户。")
        return

    lines = ["租户列表："]
    for tenant in tenants[:50]:
        status = "启用" if tenant.is_active else "停用"
        lines.append(
            f"#{tenant.id} @{tenant.username} owner={tenant.owner_user_id} "
            f"source={tenant.token_source} {status}"
        )
    await message.answer("\n".join(lines))


@admin_router.message(Command("admin_reload"))
async def admin_reload_command(message: Message, settings: Settings, tenant_manager) -> None:
    """管理员重载所有租户 polling task。"""

    if not is_admin(message, settings):
        await message.answer("无权限。")
        return

    await tenant_manager.reload_all()
    await message.answer("已重载所有启用租户 Bot。")


@admin_router.message(Command("admin_disable"))
async def admin_disable_command(message: Message, settings: Settings, tenant_manager) -> None:
    """管理员停用租户。"""

    if not is_admin(message, settings):
        await message.answer("无权限。")
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) != 2 or not args[1].isdigit():
        await message.answer("用法：/admin_disable &lt;tenant_id&gt;")
        return

    tenant_id = int(args[1])
    async with session_scope() as session:
        tenant = await session.get(TenantBot, tenant_id)
        if tenant is None:
            await message.answer("租户不存在。")
            return
        tenant.is_active = False
        tenant.last_error = "管理员手动停用"

    await tenant_manager.stop_tenant(tenant_id)
    await message.answer(f"已停用租户 #{tenant_id}。")
