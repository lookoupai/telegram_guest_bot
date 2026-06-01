from __future__ import annotations

import hashlib

from aiogram.enums import ParseMode
from aiogram.types import (
    InlineQueryResultArticle,
    InlineQueryResultPhoto,
    InputTextMessageContent,
)

from models.template import Template
from utils.keyboards import build_inline_keyboard


InlineResult = InlineQueryResultArticle | InlineQueryResultPhoto


def build_inline_results(templates: list[Template], query_text: str) -> list[InlineResult]:
    """把模板转换成 Telegram InlineQueryResult。"""

    results: list[InlineResult] = []
    for index, template in enumerate(templates):
        result_id = stable_result_id(template, query_text, index)
        reply_markup = build_inline_keyboard(template.buttons_json)

        if template.photo_url:
            results.append(
                InlineQueryResultPhoto(
                    id=result_id,
                    photo_url=template.photo_url,
                    thumbnail_url=template.photo_url,
                    title=template.title,
                    caption=template.body_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                )
            )
            continue

        results.append(
            InlineQueryResultArticle(
                id=result_id,
                title=template.title,
                description=template.body_text.replace("\n", " ")[:120],
                input_message_content=InputTextMessageContent(
                    message_text=template.body_text,
                    parse_mode=ParseMode.HTML,
                ),
                reply_markup=reply_markup,
            )
        )

    return results


def build_empty_result(query_text: str) -> InlineQueryResultArticle:
    """无模板命中时返回一个轻量提示结果。"""

    return InlineQueryResultArticle(
        id=hashlib.sha1(f"empty:{query_text}".encode("utf-8")).hexdigest()[:32],
        title="没有匹配模板",
        description="请联系机器人管理员添加关键词模板。",
        input_message_content=InputTextMessageContent(
            message_text="当前关键词没有配置模板。",
            parse_mode=ParseMode.HTML,
        ),
    )


def stable_result_id(template: Template, query_text: str, index: int) -> str:
    """生成稳定且符合 Telegram 长度限制的 result id。"""

    raw_value = f"{template.id}:{template.updated_at}:{query_text}:{index}"
    return hashlib.sha1(raw_value.encode("utf-8")).hexdigest()[:32]
