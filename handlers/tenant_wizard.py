from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Settings
from database import session_scope
from models.tenant_bot import TenantBot
from models.user import User
from services.template_service import create_template
from services.tenant_service import ensure_user, get_tenant_by_bot_id
from utils.text_format import extract_template_html

tenant_wizard_router = Router(name="tenant_wizard")


class TemplateWizard(StatesGroup):
    """租户 Bot 新增模板向导状态。"""

    keyword = State()
    title = State()
    body_text = State()
    photo_url = State()
    button = State()
    preview = State()


async def resolve_owned_tenant(
    bot: Bot,
    telegram_user,
    settings: Settings,
) -> tuple[User, TenantBot] | None:
    """按当前 Bot 和当前用户解析可管理租户。"""

    async with session_scope() as session:
        owner = await ensure_user(session, telegram_user, settings)
        tenant = await get_tenant_by_bot_id(session, bot.id)
        if tenant is None:
            return None
        if tenant.owner_user_id != owner.id and telegram_user.id not in settings.admin_ids:
            return None
        return owner, tenant


def mode_keyboard() -> InlineKeyboardMarkup:
    """匹配模式选择按钮。"""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="精确匹配", callback_data="wizard:mode:exact"),
                InlineKeyboardButton(text="模糊匹配", callback_data="wizard:mode:fuzzy"),
            ],
            [InlineKeyboardButton(text="取消", callback_data="wizard:cancel")],
        ]
    )


def skip_keyboard(callback_data: str) -> InlineKeyboardMarkup:
    """跳过当前步骤按钮。"""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="跳过", callback_data=callback_data)],
            [InlineKeyboardButton(text="取消", callback_data="wizard:cancel")],
        ]
    )


def save_keyboard() -> InlineKeyboardMarkup:
    """保存确认按钮。"""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="保存模板", callback_data="wizard:save")],
            [InlineKeyboardButton(text="取消", callback_data="wizard:cancel")],
        ]
    )


async def start_template_wizard(
    message: Message,
    bot: Bot,
    settings: Settings,
    state: FSMContext,
) -> None:
    """启动新增模板向导。"""

    if message.from_user is None:
        return

    owned = await resolve_owned_tenant(bot, message.from_user, settings)
    if owned is None:
        await message.answer("无权限或当前 Bot 尚未绑定到系统。")
        return

    _, tenant = owned
    await state.clear()
    await state.update_data(tenant_id=tenant.id, tenant_username=tenant.username)
    await state.set_state(TemplateWizard.keyword)
    await message.answer(
        "开始新增模板。\n\n"
        "第一步：请输入关键词，例如：广告\n"
        "发送 /cancel 可取消。"
    )


@tenant_wizard_router.message(Command("newtemplate"))
async def newtemplate_command(message: Message, bot: Bot, settings: Settings, state: FSMContext) -> None:
    """命令入口：新增模板向导。"""

    await start_template_wizard(message, bot, settings, state)


@tenant_wizard_router.callback_query(F.data == "tenant:new_template")
async def newtemplate_callback(callback: CallbackQuery, bot: Bot, settings: Settings, state: FSMContext) -> None:
    """按钮入口：新增模板向导。"""

    if callback.message is None or not isinstance(callback.message, Message):
        await callback.answer()
        return
    owned = await resolve_owned_tenant(bot, callback.from_user, settings)
    if owned is None:
        await callback.answer("无权限", show_alert=True)
        return

    _, tenant = owned
    await state.clear()
    await state.update_data(tenant_id=tenant.id, tenant_username=tenant.username)
    await state.set_state(TemplateWizard.keyword)
    await callback.message.answer("第一步：请输入关键词，例如：广告\n发送 /cancel 可取消。")
    await callback.answer()


@tenant_wizard_router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    """取消当前向导。"""

    await state.clear()
    await message.answer("已取消。")


@tenant_wizard_router.callback_query(F.data == "wizard:cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """按钮取消向导。"""

    await state.clear()
    if callback.message and isinstance(callback.message, Message):
        await callback.message.answer("已取消。")
    await callback.answer()


@tenant_wizard_router.message(TemplateWizard.keyword)
async def wizard_keyword(message: Message, state: FSMContext) -> None:
    """保存关键词并选择匹配模式。"""

    keyword = (message.text or "").strip()
    if not keyword:
        await message.answer("关键词不能为空，请重新输入。")
        return

    await state.update_data(keyword=keyword)
    await state.set_state(TemplateWizard.title)
    await message.answer("请选择匹配模式：", reply_markup=mode_keyboard())


@tenant_wizard_router.callback_query(F.data.in_({"wizard:mode:exact", "wizard:mode:fuzzy"}))
async def wizard_match_mode(callback: CallbackQuery, state: FSMContext) -> None:
    """保存匹配模式并进入标题步骤。"""

    match_mode = "exact" if callback.data == "wizard:mode:exact" else "fuzzy"
    await state.update_data(match_mode=match_mode)
    await state.set_state(TemplateWizard.title)
    if callback.message and isinstance(callback.message, Message):
        await callback.message.answer("请输入模板标题，例如：广告合作")
    await callback.answer()


@tenant_wizard_router.message(TemplateWizard.title)
async def wizard_title(message: Message, state: FSMContext) -> None:
    """保存标题并进入文案步骤。"""

    data = await state.get_data()
    if "match_mode" not in data:
        await message.answer("请先选择匹配模式。", reply_markup=mode_keyboard())
        return

    title = (message.text or "").strip()
    if not title:
        await message.answer("标题不能为空，请重新输入。")
        return

    await state.update_data(title=title)
    await state.set_state(TemplateWizard.body_text)
    await message.answer(
        "请输入模板文案。\n"
        "支持 HTML、Telegram 客户端超链接，也兼容 Markdown 链接：[文字](https://example.com)"
    )


@tenant_wizard_router.message(TemplateWizard.body_text)
async def wizard_body_text(message: Message, state: FSMContext) -> None:
    """保存文案并进入图片步骤。"""

    body_text = extract_template_html(message)
    if not body_text:
        await message.answer("文案不能为空，请重新输入。")
        return

    await state.update_data(body_text=body_text)
    await state.set_state(TemplateWizard.photo_url)
    await message.answer(
        "请输入图片 URL，或点击跳过。\n图片必须是公网 HTTPS URL。",
        reply_markup=skip_keyboard("wizard:skip_photo"),
    )


@tenant_wizard_router.callback_query(F.data == "wizard:skip_photo")
async def wizard_skip_photo(callback: CallbackQuery, state: FSMContext) -> None:
    """跳过图片。"""

    await state.update_data(photo_url=None)
    await state.set_state(TemplateWizard.button)
    if callback.message and isinstance(callback.message, Message):
        await callback.message.answer(
            "请输入按钮，格式：按钮文字 | https://example.com\n或点击跳过。",
            reply_markup=skip_keyboard("wizard:skip_button"),
        )
    await callback.answer()


@tenant_wizard_router.message(TemplateWizard.photo_url)
async def wizard_photo_url(message: Message, state: FSMContext) -> None:
    """保存图片 URL 并进入按钮步骤。"""

    photo_url = (message.text or "").strip()
    if photo_url and not photo_url.startswith("https://"):
        await message.answer("图片 URL 必须以 https:// 开头。请重新输入，或点击跳过。")
        return

    await state.update_data(photo_url=photo_url or None)
    await state.set_state(TemplateWizard.button)
    await message.answer(
        "请输入按钮，格式：按钮文字 | https://example.com\n或点击跳过。",
        reply_markup=skip_keyboard("wizard:skip_button"),
    )


@tenant_wizard_router.callback_query(F.data == "wizard:skip_button")
async def wizard_skip_button(callback: CallbackQuery, state: FSMContext) -> None:
    """跳过按钮并进入预览。"""

    await state.update_data(buttons_json=None)
    await send_preview(callback.message, state)
    await callback.answer()


@tenant_wizard_router.message(TemplateWizard.button)
async def wizard_button(message: Message, state: FSMContext) -> None:
    """保存按钮并进入预览。"""

    raw_button = (message.text or "").strip()
    if "|" not in raw_button:
        await message.answer("按钮格式错误。请使用：按钮文字 | https://example.com，或点击跳过。")
        return

    text, url = [item.strip() for item in raw_button.split("|", 1)]
    if not text or not url.startswith("https://"):
        await message.answer("按钮文字不能为空，URL 必须以 https:// 开头。")
        return

    await state.update_data(buttons_json=[{"text": text, "url": url}])
    await send_preview(message, state)


async def send_preview(message: Message | None, state: FSMContext) -> None:
    """发送模板保存前预览。"""

    if message is None:
        return

    data = await state.get_data()
    await state.set_state(TemplateWizard.preview)
    await message.answer(
        "请确认模板：\n\n"
        f"关键词：{data['keyword']}\n"
        f"匹配：{data['match_mode']}\n"
        f"标题：{data['title']}\n"
        f"文案：\n{data['body_text']}\n\n"
        f"图片：{data.get('photo_url') or '无'}\n"
        f"按钮：{data.get('buttons_json') or '无'}",
        reply_markup=save_keyboard(),
    )


@tenant_wizard_router.callback_query(F.data == "wizard:save")
async def wizard_save(callback: CallbackQuery, bot: Bot, settings: Settings, state: FSMContext) -> None:
    """保存模板。"""

    owned = await resolve_owned_tenant(bot, callback.from_user, settings)
    if owned is None:
        await callback.answer("无权限", show_alert=True)
        return

    _, tenant = owned
    data = await state.get_data()
    payload = {
        "keyword": data["keyword"],
        "match_mode": data["match_mode"],
        "title": data["title"],
        "body_text": data["body_text"],
        "photo_url": data.get("photo_url"),
        "buttons_json": data.get("buttons_json"),
    }

    async with session_scope() as session:
        template = await create_template(session, tenant.id, payload)

    await state.clear()
    if callback.message and isinstance(callback.message, Message):
        await callback.message.answer(f"模板已保存：#{template.id} keyword={template.keyword}")
    await callback.answer()
