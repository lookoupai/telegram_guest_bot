from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineQuery

from database import session_scope
from services.inline_result_service import build_empty_result, build_inline_results
from services.template_service import match_templates
from services.tenant_service import get_tenant_by_bot_id

logger = logging.getLogger(__name__)
tenant_inline_router = Router(name="tenant_inline")


@tenant_inline_router.inline_query()
async def answer_tenant_inline_query(inline_query: InlineQuery, bot: Bot) -> None:
    """租户 Bot 的 Inline Query 入口。

    Telegram 会把 inline_query 发给对应租户 Bot Token，不会发给管理主 Bot。
    因此这里通过 bot.id 反查租户，再读取该租户的模板。
    """

    async with session_scope() as session:
        tenant = await get_tenant_by_bot_id(session, bot.id)
        if tenant is None or not tenant.is_active:
            results = [build_empty_result(inline_query.query)]
        else:
            templates = await match_templates(session, tenant.id, inline_query.query)
            results = build_inline_results(templates, inline_query.query)
            if not results:
                results = [build_empty_result(inline_query.query)]

    logger.info(
        "租户 Inline Query: bot_id=%s query=%r results=%s",
        bot.id,
        inline_query.query,
        len(results),
    )

    try:
        await inline_query.answer(
            results=results,
            cache_time=0,
            is_personal=True,
        )
    except TelegramAPIError:
        logger.exception("Inline Query 回复失败: bot_id=%s query=%r", bot.id, inline_query.query)
