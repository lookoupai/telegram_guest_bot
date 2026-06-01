from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from database import session_scope
from services.inline_result_service import build_empty_result, build_inline_results
from services.template_service import match_templates
from services.tenant_service import get_tenant_by_bot_id

logger = logging.getLogger(__name__)
tenant_guest_router = Router(name="tenant_guest")


def normalize_guest_query(raw_text: str, tenant_username: str | None) -> str:
    """去掉 Guest 消息里的 @bot 前缀，避免精确匹配失败。"""

    query_text = raw_text.strip()
    if not tenant_username:
        return query_text

    mention = f"@{tenant_username.lower()}"
    parts = query_text.split()
    if parts and parts[0].lower() == mention:
        return " ".join(parts[1:]).strip()

    return query_text.replace(mention, "", 1).strip()


async def answer_tenant_guest_message(message: Message, bot: Bot) -> None:
    """租户 Bot 的 Guest Mode 入口。

    Guest Mode 更新里会带 guest_query_id；Bot 必须使用 answerGuestQuery 回复一个
    InlineQueryResult。这里复用同一套模板匹配和结果构造服务。
    """

    guest_query_id = getattr(message, "guest_query_id", None)
    if not guest_query_id:
        return

    raw_query_text = (message.text or message.caption or "").strip()
    async with session_scope() as session:
        tenant = await get_tenant_by_bot_id(session, bot.id)
        query_text = normalize_guest_query(raw_query_text, tenant.username if tenant else None)
        if tenant is None or not tenant.is_active:
            result = build_empty_result(query_text)
        else:
            templates = await match_templates(session, tenant.id, query_text, limit=1)
            results = build_inline_results(templates, query_text)
            result = results[0] if results else build_empty_result(query_text)

    logger.info(
        "租户 Guest Query: bot_id=%s guest_query_id=%s raw=%r normalized=%r",
        bot.id,
        guest_query_id,
        raw_query_text,
        query_text,
    )

    try:
        await bot.answer_guest_query(
            guest_query_id=guest_query_id,
            result=result,
        )
    except TelegramAPIError:
        logger.exception(
            "Guest Query 回复失败: bot_id=%s guest_query_id=%s query=%r",
            bot.id,
            guest_query_id,
            query_text,
        )


guest_message_observer = getattr(tenant_guest_router, "guest_message", None)
if guest_message_observer is not None:
    guest_message_observer.register(answer_tenant_guest_message)

tenant_guest_router.message.register(answer_tenant_guest_message, F.guest_query_id)
