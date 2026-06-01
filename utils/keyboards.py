from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_inline_keyboard(buttons_json: list | None) -> InlineKeyboardMarkup | None:
    """从 JSON 配置构造 Inline Keyboard。

    支持两种格式：
    1. [{"text": "官网", "url": "https://example.com"}]
    2. [[{"text": "官网", "url": "https://example.com"}]]
    """

    if not buttons_json:
        return None

    rows: list[list[dict]] = []
    if all(isinstance(item, dict) for item in buttons_json):
        rows = [[item] for item in buttons_json]
    else:
        rows = buttons_json

    inline_keyboard: list[list[InlineKeyboardButton]] = []
    for row in rows:
        keyboard_row: list[InlineKeyboardButton] = []
        for button in row:
            text = str(button.get("text", "")).strip()
            url = str(button.get("url", "")).strip()
            if not text or not url:
                continue
            keyboard_row.append(InlineKeyboardButton(text=text, url=url))
        if keyboard_row:
            inline_keyboard.append(keyboard_row)

    if not inline_keyboard:
        return None

    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
