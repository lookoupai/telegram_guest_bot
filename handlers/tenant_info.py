from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

tenant_info_router = Router(name="tenant_info")


async def tenant_help_command(
    message: Message,
    manager_username: str | None = None,
    tenant_username: str | None = None,
) -> None:
    """租户 Bot 的说明命令。租户 Bot 不负责创建更多 Bot。"""

    tenant_text = f"@{tenant_username}" if tenant_username else "本 Bot"
    await message.answer(
        f"{tenant_text} 是一个租户 Guest Mode 访客机器人。\n\n"
        "使用方式：在任意群组输入：\n"
        f"{tenant_text} 关键词\n\n"
        "如果没有自动回复，请打开 https://t.me/Botfather?startapp ，选择这个 Bot，"
        "进入 Bot Settings，打开 Guest Chat Mode。\n"
        "模板可以直接在这里管理；创建 Bot、Token 轮换等账号级操作仍在管理主 Bot 完成。\n"
        "当前系统核心能力是 Guest Mode 自动回复。",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="新增模板", callback_data="tenant:new_template")],
                [InlineKeyboardButton(text="查看模板", callback_data="tenant:templates")],
                [InlineKeyboardButton(text="测试关键词", callback_data="tenant:test")],
                [InlineKeyboardButton(text="写入测试模板", callback_data="tenant:seed")],
                [InlineKeyboardButton(text="刷新 Guest 状态", callback_data="tenant:status")],
                [InlineKeyboardButton(text="打开 BotFather 设置", url="https://t.me/Botfather?startapp")],
            ]
        ),
    )


tenant_info_router.message.register(tenant_help_command, CommandStart())
tenant_info_router.message.register(tenant_help_command, Command("help"))
tenant_info_router.message.register(tenant_help_command, Command("createbot"))
