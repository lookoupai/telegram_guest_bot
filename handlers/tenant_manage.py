from __future__ import annotations

import json
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Settings
from database import session_scope
from models.template import Template
from models.tenant_bot import TenantBot
from models.user import User
from services.template_service import (
    TemplateParseError,
    create_template,
    delete_template,
    get_template,
    list_templates,
    match_templates,
    parse_template_command,
    seed_sample_templates,
    set_default_template,
    toggle_template_enabled,
    update_template_field,
)
from services.tenant_service import ensure_user, get_tenant_by_bot_id
from utils.keyboards import build_inline_keyboard
from utils.text_format import extract_template_html

tenant_manage_router = Router(name="tenant_manage")


class TemplateEditWizard(StatesGroup):
    """租户 Bot 编辑模板字段状态。"""

    value = State()


class TemplateTestWizard(StatesGroup):
    """租户 Bot 测试关键词状态。"""

    query = State()


async def get_owned_tenant(
    bot: Bot,
    message: Message,
    settings: Settings,
) -> tuple[User, TenantBot] | None:
    """获取当前租户 Bot，并校验当前用户是否有管理权限。"""

    if message.from_user is None:
        return None

    async with session_scope() as session:
        owner = await ensure_user(session, message.from_user, settings)
        tenant = await get_tenant_by_bot_id(session, bot.id)
        if tenant is None:
            await message.answer("当前 Bot 尚未绑定到系统。")
            return None
        if tenant.owner_user_id != owner.id and message.from_user.id not in settings.admin_ids:
            await message.answer("无权限。请使用创建这个 Bot 的 Telegram 账号管理模板。")
            return None
        return owner, tenant


async def get_owned_tenant_from_callback(
    bot: Bot,
    callback: CallbackQuery,
    settings: Settings,
) -> tuple[User, TenantBot, Message] | None:
    """获取当前租户 Bot，并校验按钮操作者权限。"""

    if callback.message is None or not isinstance(callback.message, Message):
        await callback.answer()
        return None

    async with session_scope() as session:
        owner = await ensure_user(session, callback.from_user, settings)
        tenant = await get_tenant_by_bot_id(session, bot.id)
        if tenant is None:
            await callback.message.answer("当前 Bot 尚未绑定到系统。")
            await callback.answer()
            return None
        if tenant.owner_user_id != owner.id and callback.from_user.id not in settings.admin_ids:
            await callback.answer("无权限", show_alert=True)
            return None
        return owner, tenant, callback.message


def tenant_template_payload(tenant_username: str, payload: str) -> str:
    """把租户 Bot 内部的简化模板命令补成管理端通用格式。"""

    return f"@{tenant_username} {payload}"


def parse_template_id(callback_data: str | None, prefix: str) -> int | None:
    """从 callback_data 中解析模板 ID。"""

    if not callback_data or not callback_data.startswith(prefix):
        return None
    template_id_text = callback_data.removeprefix(prefix).split(":", 1)[0]
    return int(template_id_text) if template_id_text.isdigit() else None


def build_template_actions_keyboard(templates: list[Template]) -> InlineKeyboardMarkup:
    """构造模板管理按钮。"""

    inline_keyboard: list[list[InlineKeyboardButton]] = []
    for template in templates[:20]:
        status_text = "停用" if template.is_enabled else "启用"
        default_text = "已默认" if template.is_default else "设默认"
        inline_keyboard.extend(
            [
                [
                    InlineKeyboardButton(text=f"#{template.id} 预览", callback_data=f"tpl:preview:{template.id}"),
                    InlineKeyboardButton(text="编辑", callback_data=f"tpl:edit:{template.id}"),
                    InlineKeyboardButton(text="删除", callback_data=f"tpl:delete:{template.id}"),
                ],
                [
                    InlineKeyboardButton(text=default_text, callback_data=f"tpl:default:{template.id}"),
                    InlineKeyboardButton(text=status_text, callback_data=f"tpl:toggle:{template.id}"),
                ],
            ]
        )

    inline_keyboard.append([InlineKeyboardButton(text="新增模板", callback_data="tenant:new_template")])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def build_edit_field_keyboard(template_id: int) -> InlineKeyboardMarkup:
    """构造模板字段编辑按钮。"""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="关键词", callback_data=f"tpl:editfield:{template_id}:keyword"),
                InlineKeyboardButton(text="匹配", callback_data=f"tpl:editfield:{template_id}:mode"),
                InlineKeyboardButton(text="标题", callback_data=f"tpl:editfield:{template_id}:title"),
            ],
            [
                InlineKeyboardButton(text="文案", callback_data=f"tpl:editfield:{template_id}:text"),
                InlineKeyboardButton(text="图片", callback_data=f"tpl:editfield:{template_id}:photo"),
                InlineKeyboardButton(text="按钮", callback_data=f"tpl:editfield:{template_id}:buttons"),
            ],
            [InlineKeyboardButton(text="权重", callback_data=f"tpl:editfield:{template_id}:weight")],
        ]
    )


def build_mode_keyboard(template_id: int) -> InlineKeyboardMarkup:
    """构造匹配模式编辑按钮。"""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="精确匹配", callback_data=f"tpl:setmode:{template_id}:exact"),
                InlineKeyboardButton(text="模糊匹配", callback_data=f"tpl:setmode:{template_id}:fuzzy"),
            ]
        ]
    )


def build_clear_field_keyboard(template_id: int, field_name: str) -> InlineKeyboardMarkup:
    """构造清空字段按钮。"""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="清空当前内容", callback_data=f"tpl:clearfield:{template_id}:{field_name}")],
            [InlineKeyboardButton(text="取消", callback_data="tpl:edit_cancel")],
        ]
    )


def render_template_line(template: Template) -> str:
    """渲染模板列表单行。"""

    default_mark = " 默认" if template.is_default else ""
    enabled_mark = "启用" if template.is_enabled else "停用"
    mode_label = "精确匹配" if template.match_mode == "exact" else "模糊匹配"
    return (
        f"#{template.id} [{mode_label}] {escape(template.keyword)} "
        f"{enabled_mark}{default_mark} - {escape(template.title)}"
    )


def template_list_help_text() -> str:
    """模板列表字段说明。"""

    return (
        "说明：\n"
        "• 精确匹配：用户输入必须完全等于关键词。\n"
        "• 模糊匹配：用户输入里包含关键词就会命中。\n"
        "• 默认：没有其他模板命中时使用。\n"
        "• 标题只用于管理识别，群里主要展示文案/图片/按钮。"
    )


def render_template_detail(template: Template) -> str:
    """渲染模板详情。"""

    buttons_text = json.dumps(template.buttons_json, ensure_ascii=False) if template.buttons_json else "无"
    return (
        f"模板 #{template.id}\n"
        f"关键词：{escape(template.keyword)}\n"
        f"匹配：{escape(template.match_mode)}\n"
        f"状态：{'启用' if template.is_enabled else '停用'}\n"
        f"默认：{'是' if template.is_default else '否'}\n"
        f"权重：{template.weight}\n"
        f"标题：{escape(template.title)}\n"
        f"图片：{escape(template.photo_url or '无')}\n"
        f"按钮：{escape(buttons_text)}"
    )


def edit_field_instruction(field_name: str) -> str:
    """返回字段编辑提示。"""

    instructions = {
        "keyword": "请输入新关键词，例如：广告",
        "title": "请输入新标题，例如：广告合作",
        "text": "请输入新文案。支持 HTML、Telegram 客户端超链接，也兼容 Markdown 链接：[文字](https://example.com)",
        "photo": (
            "正在编辑图片。\n\n"
            "发送新的 HTTPS 图片 URL，例如：\n"
            "https://example.com/image.jpg\n\n"
            "如需删除图片，请点击下方“清空当前内容”。"
        ),
        "buttons": (
            "正在编辑按钮。\n\n"
            "推荐格式：\n"
            "联系我 | https://example.com\n\n"
            "高级 JSON 格式：\n"
            '[{"text":"联系我","url":"https://example.com"}]\n\n'
            "如需删除按钮，请点击下方“清空当前内容”。"
        ),
        "weight": "请输入权重，大于 0 的整数，例如：5",
    }
    return instructions.get(field_name, "请输入新值。")


async def send_tenant_status(message: Message, tenant: TenantBot) -> None:
    """发送租户运行状态。"""

    async with session_scope() as session:
        templates = await list_templates(session, tenant.id, include_disabled=True)

    enabled_templates = sum(1 for template in templates if template.is_enabled)
    default_template = next((template for template in templates if template.is_default), None)
    default_line = f"默认模板：#{default_template.id}" if default_template else "默认模板：未设置"
    await message.answer(
        f"租户状态：@{escape(tenant.username)}\n"
        f"状态：{'启用' if tenant.is_active else '停用'}\n"
        f"Guest Mode：{tenant.supports_guest_queries}\n"
        f"Inline Mode：{tenant.supports_inline_queries}\n"
        f"模板：{enabled_templates}/{len(templates)} 启用\n"
        f"{default_line}\n"
        f"最后错误：{escape(tenant.last_error or '无')}\n\n"
        "如果 Guest Mode 不是 True：打开 https://t.me/Botfather?startapp → 选择本 Bot → "
        "Bot Settings → Guest Chat Mode → 打开。"
    )


async def send_template_list(message: Message, tenant: TenantBot) -> None:
    """发送模板列表。"""

    async with session_scope() as session:
        templates = await list_templates(session, tenant.id, include_disabled=True)

    if not templates:
        await message.answer(
            "暂无模板。可以点击新增模板，或先写入测试模板。",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="新增模板", callback_data="tenant:new_template")],
                    [InlineKeyboardButton(text="写入测试模板", callback_data="tenant:seed")],
                ]
            ),
        )
        return

    lines = [
        f"@{escape(tenant.username)} 模板：",
        "点击下方按钮可预览、编辑、删除、设默认或启停。",
        "",
        template_list_help_text(),
        "",
    ]
    for template in templates[:50]:
        lines.append(render_template_line(template))
    await message.answer("\n".join(lines), reply_markup=build_template_actions_keyboard(templates))


async def send_template_preview(message: Message, template: Template) -> None:
    """发送模板真实效果预览。"""

    reply_markup = build_inline_keyboard(template.buttons_json)
    try:
        if template.photo_url:
            await message.answer_photo(
                photo=template.photo_url,
                caption=template.body_text,
                reply_markup=reply_markup,
            )
            return
        await message.answer(template.body_text, reply_markup=reply_markup)
    except TelegramAPIError as exc:
        await message.answer(f"预览发送失败，通常是图片 URL 不可访问或 HTML 格式错误：{exc}")


async def send_keyword_test_result(message: Message, tenant: TenantBot, query_text: str) -> None:
    """按 Guest Mode 匹配规则测试一个关键词。"""

    async with session_scope() as session:
        templates = await match_templates(session, tenant.id, query_text, limit=1)

    if not templates:
        await message.answer(f"未命中模板：{escape(query_text)}")
        return

    template = templates[0]
    await message.answer(f"测试关键词：{escape(query_text)}\n命中模板：\n{render_template_line(template)}")
    await send_template_preview(message, template)


@tenant_manage_router.message(Command("addtemplate"))
async def tenant_addtemplate_command(
    message: Message,
    command: CommandObject,
    bot: Bot,
    settings: Settings,
) -> None:
    """在租户 Bot 内直接添加模板。"""

    owned = await get_owned_tenant(bot, message, settings)
    if owned is None:
        return
    _, tenant = owned

    payload = command.args or ""
    if not payload:
        await message.answer(
            "用法：\n"
            "/addtemplate =广告 | 广告标题 | <b>广告文案</b> | https://image.jpg | "
            '[{"text":"联系","url":"https://example.com"}]\n\n'
            "关键词前缀：= 精确匹配，~ 模糊匹配；不写默认模糊匹配。"
        )
        return

    try:
        parsed_payload = parse_template_command(tenant_template_payload(tenant.username, payload))
    except TemplateParseError as exc:
        await message.answer(str(exc))
        return

    async with session_scope() as session:
        template = await create_template(session, tenant.id, parsed_payload)

    await message.answer(f"模板已添加：#{template.id} keyword={template.keyword}")


@tenant_manage_router.message(Command("mytemplates"))
async def tenant_mytemplates_command(message: Message, bot: Bot, settings: Settings) -> None:
    """在租户 Bot 内查看模板。"""

    owned = await get_owned_tenant(bot, message, settings)
    if owned is None:
        return
    _, tenant = owned
    await send_template_list(message, tenant)


@tenant_manage_router.message(Command("status"))
async def tenant_status_command(message: Message, bot: Bot, settings: Settings) -> None:
    """在租户 Bot 内查看 Guest Mode 状态。"""

    owned = await get_owned_tenant(bot, message, settings)
    if owned is None:
        return
    _, tenant = owned
    await send_tenant_status(message, tenant)


@tenant_manage_router.message(Command("test"))
async def tenant_test_command(
    message: Message,
    command: CommandObject,
    bot: Bot,
    settings: Settings,
    state: FSMContext,
) -> None:
    """在租户 Bot 内测试关键词匹配效果。"""

    owned = await get_owned_tenant(bot, message, settings)
    if owned is None:
        return
    _, tenant = owned

    query_text = (command.args or "").strip()
    if query_text:
        await send_keyword_test_result(message, tenant, query_text)
        return

    await state.clear()
    await state.update_data(tenant_id=tenant.id)
    await state.set_state(TemplateTestWizard.query)
    await message.answer("请输入要测试的关键词，例如：广告\n发送 /cancel 可取消。")


@tenant_manage_router.message(Command("seedtemplates"))
async def tenant_seedtemplates_command(message: Message, bot: Bot, settings: Settings) -> None:
    """在租户 Bot 内写入测试模板。"""

    owned = await get_owned_tenant(bot, message, settings)
    if owned is None:
        return
    _, tenant = owned

    async with session_scope() as session:
        created_count = await seed_sample_templates(session, tenant.id)

    if created_count == 0:
        await message.answer("当前 Bot 已有模板，未重复写入示例模板。")
        return
    await message.answer(f"已写入 {created_count} 个测试模板：广告、推广、你好。")


@tenant_manage_router.message(Command("edittemplate"))
async def tenant_edittemplate_command(
    message: Message,
    command: CommandObject,
    bot: Bot,
    settings: Settings,
) -> None:
    """在租户 Bot 内编辑模板。"""

    owned = await get_owned_tenant(bot, message, settings)
    if owned is None:
        return
    _, tenant = owned

    args = (command.args or "").split(maxsplit=2)
    if len(args) != 3 or not args[0].isdigit():
        await message.answer(
            "用法：/edittemplate &lt;template_id&gt; &lt;field&gt; &lt;value&gt;\n"
            "字段：keyword/mode/title/text/photo/buttons/weight/enabled"
        )
        return

    try:
        async with session_scope() as session:
            updated = await update_template_field(
                session,
                template_id=int(args[0]),
                owner_tenant_ids={tenant.id},
                field_name=args[1],
                raw_value=args[2],
            )
    except TemplateParseError as exc:
        await message.answer(str(exc))
        return

    await message.answer("模板已更新。" if updated else "模板不存在或无权限。")


@tenant_manage_router.message(Command("deltemplate"))
async def tenant_deltemplate_command(
    message: Message,
    command: CommandObject,
    bot: Bot,
    settings: Settings,
) -> None:
    """在租户 Bot 内删除模板。"""

    owned = await get_owned_tenant(bot, message, settings)
    if owned is None:
        return
    _, tenant = owned

    template_id_text = (command.args or "").strip()
    if not template_id_text.isdigit():
        await message.answer("用法：/deltemplate &lt;template_id&gt;")
        return

    async with session_scope() as session:
        deleted = await delete_template(
            session,
            template_id=int(template_id_text),
            owner_tenant_ids={tenant.id},
        )

    await message.answer("模板已删除。" if deleted else "模板不存在或无权限。")


@tenant_manage_router.message(Command("setdefault"))
async def tenant_setdefault_command(
    message: Message,
    command: CommandObject,
    bot: Bot,
    settings: Settings,
) -> None:
    """在租户 Bot 内设置默认模板。"""

    owned = await get_owned_tenant(bot, message, settings)
    if owned is None:
        return
    _, tenant = owned

    template_id_text = (command.args or "").strip()
    if not template_id_text.isdigit():
        await message.answer("用法：/setdefault &lt;template_id&gt;")
        return

    async with session_scope() as session:
        updated = await set_default_template(
            session,
            template_id=int(template_id_text),
            owner_tenant_ids={tenant.id},
        )

    await message.answer("默认模板已更新。" if updated else "模板不存在或无权限。")


@tenant_manage_router.callback_query(F.data == "tenant:seed")
async def tenant_seed_callback(callback: CallbackQuery, bot: Bot, settings: Settings) -> None:
    """按钮：写入测试模板。"""

    owned = await get_owned_tenant_from_callback(bot, callback, settings)
    if owned is None:
        return
    _, tenant, message = owned

    async with session_scope() as session:
        created_count = await seed_sample_templates(session, tenant.id)

    if created_count == 0:
        await message.answer("当前 Bot 已有模板，未重复写入示例模板。")
    else:
        await message.answer(f"已写入 {created_count} 个测试模板：广告、推广、你好。")
    await callback.answer()


@tenant_manage_router.callback_query(F.data == "tenant:templates")
async def tenant_templates_callback(callback: CallbackQuery, bot: Bot, settings: Settings) -> None:
    """按钮：查看模板。"""

    owned = await get_owned_tenant_from_callback(bot, callback, settings)
    if owned is None:
        return
    _, tenant, message = owned
    await send_template_list(message, tenant)
    await callback.answer()


@tenant_manage_router.callback_query(F.data == "tenant:test")
async def tenant_test_callback(
    callback: CallbackQuery,
    bot: Bot,
    settings: Settings,
    state: FSMContext,
) -> None:
    """按钮：进入关键词测试状态。"""

    owned = await get_owned_tenant_from_callback(bot, callback, settings)
    if owned is None:
        return
    _, tenant, message = owned

    await state.clear()
    await state.update_data(tenant_id=tenant.id)
    await state.set_state(TemplateTestWizard.query)
    await message.answer("请输入要测试的关键词，例如：广告\n发送 /cancel 可取消。")
    await callback.answer()


@tenant_manage_router.message(TemplateTestWizard.query)
async def tenant_test_query_message(message: Message, bot: Bot, settings: Settings, state: FSMContext) -> None:
    """保存测试关键词并发送匹配结果。"""

    owned = await get_owned_tenant(bot, message, settings)
    if owned is None:
        await state.clear()
        return
    _, tenant = owned

    data = await state.get_data()
    if data.get("tenant_id") != tenant.id:
        await state.clear()
        await message.answer("测试状态已失效，请重新操作。")
        return

    query_text = (message.text or "").strip()
    if not query_text:
        await message.answer("关键词不能为空，请重新输入。")
        return

    await state.clear()
    await send_keyword_test_result(message, tenant, query_text)


@tenant_manage_router.callback_query(F.data == "tenant:status")
async def tenant_status_callback(callback: CallbackQuery, bot: Bot, settings: Settings) -> None:
    """按钮：刷新并查看 Guest Mode 状态。"""

    owned = await get_owned_tenant_from_callback(bot, callback, settings)
    if owned is None:
        return
    _, tenant, message = owned

    me = await bot.get_me()
    async with session_scope() as session:
        current_tenant = await session.get(TenantBot, tenant.id)
        if current_tenant is not None:
            current_tenant.username = (me.username or current_tenant.username).lower()
            current_tenant.first_name = me.first_name
            current_tenant.supports_guest_queries = me.supports_guest_queries
            current_tenant.supports_inline_queries = me.supports_inline_queries
            current_tenant.last_error = None
            tenant.username = current_tenant.username
            tenant.first_name = current_tenant.first_name
            tenant.supports_guest_queries = current_tenant.supports_guest_queries
            tenant.supports_inline_queries = current_tenant.supports_inline_queries
            tenant.last_error = current_tenant.last_error

    await send_tenant_status(message, tenant)
    await callback.answer()


@tenant_manage_router.callback_query(F.data.startswith("tpl:preview:"))
async def template_preview_callback(callback: CallbackQuery, bot: Bot, settings: Settings) -> None:
    """按钮：预览模板。"""

    owned = await get_owned_tenant_from_callback(bot, callback, settings)
    template_id = parse_template_id(callback.data, "tpl:preview:")
    if owned is None or template_id is None:
        return
    _, tenant, message = owned

    async with session_scope() as session:
        template = await get_template(session, template_id, {tenant.id})

    if template is None:
        await callback.answer("模板不存在或无权限", show_alert=True)
        return

    await message.answer(render_template_detail(template))
    await send_template_preview(message, template)
    await callback.answer()


@tenant_manage_router.callback_query(F.data.startswith("tpl:edit:"))
async def template_edit_callback(callback: CallbackQuery, bot: Bot, settings: Settings) -> None:
    """按钮：选择要编辑的字段。"""

    owned = await get_owned_tenant_from_callback(bot, callback, settings)
    template_id = parse_template_id(callback.data, "tpl:edit:")
    if owned is None or template_id is None:
        return
    _, tenant, message = owned

    async with session_scope() as session:
        template = await get_template(session, template_id, {tenant.id})

    if template is None:
        await callback.answer("模板不存在或无权限", show_alert=True)
        return

    await message.answer(
        f"选择要编辑的字段：\n{render_template_line(template)}",
        reply_markup=build_edit_field_keyboard(template.id),
    )
    await callback.answer()


@tenant_manage_router.callback_query(F.data.startswith("tpl:editfield:"))
async def template_edit_field_callback(
    callback: CallbackQuery,
    bot: Bot,
    settings: Settings,
    state: FSMContext,
) -> None:
    """按钮：进入字段编辑状态。"""

    owned = await get_owned_tenant_from_callback(bot, callback, settings)
    if owned is None:
        return
    _, tenant, message = owned

    parts = (callback.data or "").split(":")
    if len(parts) != 4 or not parts[2].isdigit():
        await callback.answer("参数错误", show_alert=True)
        return

    template_id = int(parts[2])
    field_name = parts[3]
    async with session_scope() as session:
        template = await get_template(session, template_id, {tenant.id})

    if template is None:
        await callback.answer("模板不存在或无权限", show_alert=True)
        return

    if field_name == "mode":
        await message.answer("请选择匹配模式：", reply_markup=build_mode_keyboard(template_id))
        await callback.answer()
        return

    await state.clear()
    await state.update_data(template_id=template_id, tenant_id=tenant.id, field_name=field_name)
    await state.set_state(TemplateEditWizard.value)
    reply_markup = build_clear_field_keyboard(template_id, field_name) if field_name in {"photo", "buttons"} else None
    await message.answer(edit_field_instruction(field_name) + "\n\n发送 /cancel 可取消。", reply_markup=reply_markup)
    await callback.answer()


@tenant_manage_router.callback_query(F.data.startswith("tpl:clearfield:"))
async def template_clear_field_callback(
    callback: CallbackQuery,
    bot: Bot,
    settings: Settings,
    state: FSMContext,
) -> None:
    """按钮：清空图片或按钮字段。"""

    owned = await get_owned_tenant_from_callback(bot, callback, settings)
    if owned is None:
        return
    _, tenant, message = owned

    parts = (callback.data or "").split(":")
    if len(parts) != 4 or not parts[2].isdigit() or parts[3] not in {"photo", "buttons"}:
        await callback.answer("参数错误", show_alert=True)
        return

    try:
        async with session_scope() as session:
            updated = await update_template_field(session, int(parts[2]), {tenant.id}, parts[3], "-")
    except TemplateParseError as exc:
        await message.answer(str(exc))
        await callback.answer()
        return

    await state.clear()
    await message.answer("已清空。" if updated else "模板不存在或无权限。")
    await send_template_list(message, tenant)
    await callback.answer()


@tenant_manage_router.callback_query(F.data == "tpl:edit_cancel")
async def template_edit_cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """按钮：取消字段编辑。"""

    await state.clear()
    if callback.message and isinstance(callback.message, Message):
        await callback.message.answer("已取消编辑。")
    await callback.answer()


@tenant_manage_router.callback_query(F.data.startswith("tpl:setmode:"))
async def template_set_mode_callback(callback: CallbackQuery, bot: Bot, settings: Settings) -> None:
    """按钮：设置模板匹配模式。"""

    owned = await get_owned_tenant_from_callback(bot, callback, settings)
    if owned is None:
        return
    _, tenant, message = owned

    parts = (callback.data or "").split(":")
    if len(parts) != 4 or not parts[2].isdigit() or parts[3] not in {"exact", "fuzzy"}:
        await callback.answer("参数错误", show_alert=True)
        return

    try:
        async with session_scope() as session:
            updated = await update_template_field(session, int(parts[2]), {tenant.id}, "mode", parts[3])
    except TemplateParseError as exc:
        await message.answer(str(exc))
        await callback.answer()
        return

    await message.answer("匹配模式已更新。" if updated else "模板不存在或无权限。")
    await send_template_list(message, tenant)
    await callback.answer()


@tenant_manage_router.message(TemplateEditWizard.value)
async def template_edit_value_message(message: Message, bot: Bot, settings: Settings, state: FSMContext) -> None:
    """保存按钮化编辑输入的新值。"""

    owned = await get_owned_tenant(bot, message, settings)
    if owned is None:
        await state.clear()
        return
    _, tenant = owned

    data = await state.get_data()
    template_id = data.get("template_id")
    tenant_id = data.get("tenant_id")
    field_name = data.get("field_name")
    raw_value = extract_template_html(message) if field_name == "text" else (message.text or "").strip()
    if not isinstance(template_id, int) or tenant_id != tenant.id or not isinstance(field_name, str):
        await state.clear()
        await message.answer("编辑状态已失效，请重新操作。")
        return

    try:
        async with session_scope() as session:
            updated = await update_template_field(session, template_id, {tenant.id}, field_name, raw_value)
    except TemplateParseError as exc:
        await message.answer(str(exc))
        return

    await state.clear()
    await message.answer("模板已更新。" if updated else "模板不存在或无权限。")
    await send_template_list(message, tenant)


@tenant_manage_router.callback_query(F.data.startswith("tpl:default:"))
async def template_default_callback(callback: CallbackQuery, bot: Bot, settings: Settings) -> None:
    """按钮：设置默认模板。"""

    owned = await get_owned_tenant_from_callback(bot, callback, settings)
    template_id = parse_template_id(callback.data, "tpl:default:")
    if owned is None or template_id is None:
        return
    _, tenant, message = owned

    async with session_scope() as session:
        updated = await set_default_template(session, template_id, {tenant.id})

    await message.answer("默认模板已更新。" if updated else "模板不存在或无权限。")
    await send_template_list(message, tenant)
    await callback.answer()


@tenant_manage_router.callback_query(F.data.startswith("tpl:toggle:"))
async def template_toggle_callback(callback: CallbackQuery, bot: Bot, settings: Settings) -> None:
    """按钮：启用或停用模板。"""

    owned = await get_owned_tenant_from_callback(bot, callback, settings)
    template_id = parse_template_id(callback.data, "tpl:toggle:")
    if owned is None or template_id is None:
        return
    _, tenant, message = owned

    async with session_scope() as session:
        template = await toggle_template_enabled(session, template_id, {tenant.id})
        status_text = "启用" if template and template.is_enabled else "停用"

    await message.answer(f"模板已{status_text}。" if template else "模板不存在或无权限。")
    await send_template_list(message, tenant)
    await callback.answer()


@tenant_manage_router.callback_query(F.data.startswith("tpl:delete:"))
async def template_delete_callback(callback: CallbackQuery, bot: Bot, settings: Settings) -> None:
    """按钮：删除前确认。"""

    owned = await get_owned_tenant_from_callback(bot, callback, settings)
    template_id = parse_template_id(callback.data, "tpl:delete:")
    if owned is None or template_id is None:
        return
    _, tenant, message = owned

    async with session_scope() as session:
        template = await get_template(session, template_id, {tenant.id})

    if template is None:
        await callback.answer("模板不存在或无权限", show_alert=True)
        return

    await message.answer(
        f"确认删除模板？\n{render_template_line(template)}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="确认删除", callback_data=f"tpl:delete_confirm:{template.id}")],
                [InlineKeyboardButton(text="取消", callback_data="tpl:delete_cancel")],
            ]
        ),
    )
    await callback.answer()


@tenant_manage_router.callback_query(F.data.startswith("tpl:delete_confirm:"))
async def template_delete_confirm_callback(callback: CallbackQuery, bot: Bot, settings: Settings) -> None:
    """按钮：确认删除模板。"""

    owned = await get_owned_tenant_from_callback(bot, callback, settings)
    template_id = parse_template_id(callback.data, "tpl:delete_confirm:")
    if owned is None or template_id is None:
        return
    _, tenant, message = owned

    async with session_scope() as session:
        deleted = await delete_template(session, template_id, {tenant.id})

    await message.answer("模板已删除。" if deleted else "模板不存在或无权限。")
    await send_template_list(message, tenant)
    await callback.answer()


@tenant_manage_router.callback_query(F.data == "tpl:delete_cancel")
async def template_delete_cancel_callback(callback: CallbackQuery) -> None:
    """按钮：取消删除。"""

    if callback.message and isinstance(callback.message, Message):
        await callback.message.answer("已取消删除。")
    await callback.answer()
