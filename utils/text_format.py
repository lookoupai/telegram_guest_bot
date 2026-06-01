from __future__ import annotations

import re

from aiogram.types import Message

MARKDOWN_LINK_RE = re.compile(r"\[([^\]\n]+)]\((https?://[^)\s]+|tg://[^)\s]+)\)")


def extract_template_html(message: Message) -> str:
    """提取模板文案，优先保留 Telegram 客户端富文本实体为 HTML。

    Telegram 客户端手动设置的“超链接”会保存在 message.entities 里；直接读取
    message.text 会丢失 URL。aiogram 的 html_text 会把 text_link 转成 <a href="">。
    如果用户输入 Markdown 链接，则转换常见的 [文字](https://...) 写法。
    """

    if message.entities or message.caption_entities:
        return (message.html_text or message.html_caption or "").strip()

    raw_text = (message.text or message.caption or "").strip()
    return markdown_links_to_html(raw_text)


def markdown_links_to_html(text: str) -> str:
    """把常见 Markdown 链接转成 Telegram HTML 链接。"""

    return MARKDOWN_LINK_RE.sub(r'<a href="\2">\1</a>', text)
