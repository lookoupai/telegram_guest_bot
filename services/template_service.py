from __future__ import annotations

import json
import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.template import MatchMode, Template


class TemplateParseError(ValueError):
    """模板命令解析失败。"""


SAMPLE_TEMPLATES: tuple[dict, ...] = (
    {
        "keyword": "广告",
        "match_mode": MatchMode.EXACT.value,
        "title": "广告合作",
        "body_text": "📣 <b>广告合作</b>\n\n这是 Guest Mode 自动回复示例，可在管理 Bot 中修改。",
        "photo_url": "https://placehold.co/1024x576.jpg?text=Guest+Bot+Ads",
        "buttons_json": [{"text": "联系我", "url": "https://example.com/contact"}],
    },
    {
        "keyword": "推广",
        "match_mode": MatchMode.FUZZY.value,
        "title": "推广服务",
        "body_text": "🚀 <b>推广服务</b>\n\n这里可以放推广文案、报价和联系方式。",
        "photo_url": None,
        "buttons_json": [{"text": "查看详情", "url": "https://example.com"}],
    },
    {
        "keyword": "你好",
        "match_mode": MatchMode.FUZZY.value,
        "title": "欢迎消息",
        "body_text": "你好，我是 Guest Mode 访客机器人。",
        "photo_url": None,
        "buttons_json": None,
    },
)


def parse_template_command(payload: str) -> dict:
    """解析 /addtemplate 命令。

    格式：
    /addtemplate @bot =广告 | 广告标题 | 文案 | https://image.jpg | [{"text":"联系","url":"https://example.com"}]

    keyword 以 "=" 开头表示精确匹配，以 "~" 开头表示模糊匹配，默认模糊匹配。
    图片 URL 和按钮 JSON 都是可选字段。
    """

    parts = [part.strip() for part in payload.split("|")]
    if len(parts) < 3:
        raise TemplateParseError("格式错误：至少需要 @bot、关键词、标题、文案。")

    first_part = parts[0].split(maxsplit=1)
    if len(first_part) != 2:
        raise TemplateParseError("格式错误：第一段应为 '@bot 关键词'。")

    bot_username, raw_keyword = first_part
    match_mode = MatchMode.FUZZY.value
    keyword = raw_keyword.strip()
    if keyword.startswith("="):
        match_mode = MatchMode.EXACT.value
        keyword = keyword[1:].strip()
    elif keyword.startswith("~"):
        match_mode = MatchMode.FUZZY.value
        keyword = keyword[1:].strip()

    if not bot_username.startswith("@"):
        raise TemplateParseError("Bot 用户名必须以 @ 开头。")
    if not keyword:
        raise TemplateParseError("关键词不能为空。")

    title = parts[1]
    body_text = parts[2]
    if not title or not body_text:
        raise TemplateParseError("标题和文案不能为空。")

    photo_url = parts[3] if len(parts) >= 4 and parts[3] else None
    buttons_json = None
    if len(parts) >= 5 and parts[4]:
        try:
            buttons_json = json.loads(parts[4])
        except json.JSONDecodeError as exc:
            raise TemplateParseError(f"按钮 JSON 格式错误：{exc}") from exc

    return {
        "bot_username": bot_username,
        "keyword": keyword,
        "match_mode": match_mode,
        "title": title,
        "body_text": body_text,
        "photo_url": photo_url,
        "buttons_json": buttons_json,
    }


async def create_template(
    session: AsyncSession,
    tenant_id: int,
    payload: dict,
) -> Template:
    """创建模板。"""

    photo_url = normalize_photo_url(payload.get("photo_url"))
    buttons_json = normalize_buttons_json(payload.get("buttons_json"))
    template = Template(
        tenant_id=tenant_id,
        keyword=payload["keyword"],
        match_mode=payload["match_mode"],
        title=payload["title"],
        body_text=payload["body_text"],
        photo_url=photo_url,
        buttons_json=buttons_json,
        weight=1,
        is_default=False,
        is_enabled=True,
    )
    session.add(template)
    await session.flush()
    return template


async def seed_sample_templates(session: AsyncSession, tenant_id: int) -> int:
    """为空租户写入示例模板，便于立刻验证 Guest Mode。"""

    existing_templates = await list_templates(session, tenant_id, include_disabled=True)
    if existing_templates:
        return 0

    created_count = 0
    for payload in SAMPLE_TEMPLATES:
        template = Template(
            tenant_id=tenant_id,
            keyword=payload["keyword"],
            match_mode=payload["match_mode"],
            title=payload["title"],
            body_text=payload["body_text"],
            photo_url=payload["photo_url"],
            buttons_json=payload["buttons_json"],
            weight=1,
            is_default=payload["keyword"] == "你好",
            is_enabled=True,
        )
        session.add(template)
        created_count += 1
    await session.flush()
    return created_count


async def list_templates(
    session: AsyncSession,
    tenant_id: int,
    include_disabled: bool = False,
) -> list[Template]:
    """列出租户模板。"""

    statement = select(Template).where(Template.tenant_id == tenant_id)
    if not include_disabled:
        statement = statement.where(Template.is_enabled.is_(True))
    statement = statement.order_by(Template.is_default.desc(), Template.created_at.desc())
    result = await session.execute(statement)
    return list(result.scalars().all())


async def get_template(
    session: AsyncSession,
    template_id: int,
    owner_tenant_ids: set[int],
) -> Template | None:
    """按权限获取单个模板。"""

    template = await session.get(Template, template_id)
    if template is None or template.tenant_id not in owner_tenant_ids:
        return None
    return template


async def delete_template(session: AsyncSession, template_id: int, owner_tenant_ids: set[int]) -> bool:
    """删除当前用户名下的模板。"""

    template = await session.get(Template, template_id)
    if template is None or template.tenant_id not in owner_tenant_ids:
        return False
    await session.delete(template)
    return True


async def set_default_template(
    session: AsyncSession,
    template_id: int,
    owner_tenant_ids: set[int],
) -> bool:
    """设置默认模板。"""

    template = await session.get(Template, template_id)
    if template is None or template.tenant_id not in owner_tenant_ids:
        return False

    templates = await list_templates(session, template.tenant_id, include_disabled=True)
    for item in templates:
        item.is_default = item.id == template.id
    return True


async def toggle_template_enabled(
    session: AsyncSession,
    template_id: int,
    owner_tenant_ids: set[int],
) -> Template | None:
    """切换模板启用状态。"""

    template = await get_template(session, template_id, owner_tenant_ids)
    if template is None:
        return None
    template.is_enabled = not template.is_enabled
    if not template.is_enabled:
        template.is_default = False
    return template


async def update_template_field(
    session: AsyncSession,
    template_id: int,
    owner_tenant_ids: set[int],
    field_name: str,
    raw_value: str,
) -> bool:
    """更新模板单个字段。"""

    template = await session.get(Template, template_id)
    if template is None or template.tenant_id not in owner_tenant_ids:
        return False

    normalized_field = field_name.lower()
    value = raw_value.strip()

    if normalized_field in {"keyword", "kw"}:
        if not value:
            raise TemplateParseError("关键词不能为空。")
        template.keyword = value
        return True

    if normalized_field in {"mode", "match_mode"}:
        if value not in {MatchMode.EXACT.value, MatchMode.FUZZY.value}:
            raise TemplateParseError("匹配模式只能是 exact 或 fuzzy。")
        template.match_mode = value
        return True

    if normalized_field == "title":
        if not value:
            raise TemplateParseError("标题不能为空。")
        template.title = value
        return True

    if normalized_field in {"text", "body", "body_text"}:
        if not value:
            raise TemplateParseError("文案不能为空。")
        template.body_text = value
        return True

    if normalized_field in {"photo", "photo_url"}:
        template.photo_url = None if value == "-" else normalize_photo_url(value)
        return True

    if normalized_field in {"buttons", "buttons_json"}:
        if value == "-":
            template.buttons_json = None
            return True
        if "|" in value and not value.startswith(("[", "{")):
            text, url = [item.strip() for item in value.split("|", 1)]
            template.buttons_json = normalize_buttons_json([{"text": text, "url": url}])
            return True
        try:
            template.buttons_json = normalize_buttons_json(json.loads(value))
        except json.JSONDecodeError as exc:
            raise TemplateParseError("按钮格式错误。请使用：按钮文字 | https://example.com") from exc
        return True

    if normalized_field == "weight":
        if not value.isdigit() or int(value) < 1:
            raise TemplateParseError("权重必须是大于 0 的整数。")
        template.weight = int(value)
        return True

    if normalized_field in {"enabled", "is_enabled"}:
        if value.lower() not in {"1", "0", "true", "false", "yes", "no", "on", "off"}:
            raise TemplateParseError("enabled 只能是 true/false。")
        template.is_enabled = value.lower() in {"1", "true", "yes", "on"}
        return True

    raise TemplateParseError("不支持的字段。可编辑：keyword/mode/title/text/photo/buttons/weight/enabled。")


def normalize_photo_url(value: str | None) -> str | None:
    """校验图片 URL；Guest/Inline 图片必须可被 Telegram 公网访问。"""

    if not value:
        return None
    photo_url = value.strip()
    if not photo_url:
        return None
    if not photo_url.startswith("https://"):
        raise TemplateParseError("图片 URL 必须以 https:// 开头。")
    return photo_url


def normalize_buttons_json(value: list | None) -> list | None:
    """校验按钮 JSON，支持单列和多行两种结构。"""

    if value is None:
        return None
    if not isinstance(value, list):
        raise TemplateParseError("按钮配置必须是 JSON 数组。")

    rows = [[item] for item in value] if all(isinstance(item, dict) for item in value) else value
    normalized_rows: list[list[dict]] = []
    for row in rows:
        if not isinstance(row, list):
            raise TemplateParseError("按钮多行配置必须是二维数组。")
        normalized_row: list[dict] = []
        for button in row:
            if not isinstance(button, dict):
                raise TemplateParseError("每个按钮必须是对象，包含 text 和 url。")
            text = str(button.get("text", "")).strip()
            url = str(button.get("url", "")).strip()
            if not text or not url:
                raise TemplateParseError("按钮 text 和 url 不能为空。")
            if not url.startswith(("https://", "http://", "tg://")):
                raise TemplateParseError("按钮 URL 必须以 https://、http:// 或 tg:// 开头。")
            normalized_row.append({"text": text, "url": url})
        if normalized_row:
            normalized_rows.append(normalized_row)

    if not normalized_rows:
        return None
    if all(len(row) == 1 for row in normalized_rows):
        return [row[0] for row in normalized_rows]
    return normalized_rows


async def match_templates(
    session: AsyncSession,
    tenant_id: int,
    query_text: str,
    limit: int = 10,
) -> list[Template]:
    """根据 query 匹配模板，优先精确，再模糊，最后默认。"""

    templates = await list_templates(session, tenant_id)
    normalized_query = query_text.strip().lower()

    exact_matches = [
        template
        for template in templates
        if template.match_mode == MatchMode.EXACT.value
        and normalized_query == template.keyword.lower()
    ]
    fuzzy_matches = [
        template
        for template in templates
        if template.match_mode == MatchMode.FUZZY.value
        and template.keyword.lower() in normalized_query
    ]
    default_matches = [template for template in templates if template.is_default]

    matched = exact_matches or fuzzy_matches or default_matches
    return weighted_shuffle(matched)[:limit]


def weighted_shuffle(templates: list[Template]) -> list[Template]:
    """按权重随机排序，避免固定模板永远排第一。"""

    return sorted(
        templates,
        key=lambda template: random.random() / max(template.weight, 1),
    )
