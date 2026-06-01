from __future__ import annotations

import logging
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, ManagedBotUpdated, Message

from config import Settings
from database import session_scope
from models.tenant_bot import TokenSource
from services.template_service import (
    TemplateParseError,
    create_template,
    delete_template,
    list_templates,
    parse_template_command,
    seed_sample_templates,
    set_default_template,
    update_template_field,
)
from services.tenant_service import (
    TenantTokenError,
    ensure_user,
    get_tenant_by_username,
    list_owner_tenants,
    upsert_tenant_bot,
    validate_bot_token,
)
from utils.crypto import TokenCipher

logger = logging.getLogger(__name__)
manage_router = Router(name="manage")


def build_help_text() -> str:
    """管理后台帮助文本。"""

    return (
        "多租户 Guest Mode 访客机器人管理台已启动。\n\n"
        "常用命令：\n"
        "/createbot - 创建受管理的租户 Bot\n"
        "/addtoken &lt;token&gt; - 手动绑定已有 Bot Token\n"
        "/mybots - 查看我的租户 Bot\n"
        "/tenantstatus @bot - 查看租户状态\n"
        "/refreshbot @bot - 刷新 Guest 状态并重启租户 Bot\n"
        "/seedtemplates @bot - 写入测试模板\n"
        "/addtemplate - 查看模板添加格式\n"
        "/edittemplate &lt;id&gt; &lt;field&gt; &lt;value&gt; - 编辑模板\n"
        "/mytemplates @bot - 查看模板\n"
        "/rotatetoken @bot - 轮换受管理 Bot Token\n"
        "/setdefault &lt;template_id&gt; - 设置默认模板"
    )


def build_master_menu() -> InlineKeyboardMarkup:
    """管理主 Bot 菜单按钮。"""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="创建受管理 Bot", callback_data="master:createbot")],
            [InlineKeyboardButton(text="我的租户 Bot", callback_data="master:mybots")],
            [InlineKeyboardButton(text="打开 BotFather 设置", url="https://t.me/Botfather?startapp")],
            [InlineKeyboardButton(text="帮助", callback_data="master:help")],
        ]
    )


def build_owner_bots_keyboard(tenants) -> InlineKeyboardMarkup | None:
    """为租户列表构造快捷打开按钮。"""

    if not tenants:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"打开 @{tenant.username}", url=f"https://t.me/{tenant.username}")]
            for tenant in tenants[:20]
        ]
    )


async def delete_sensitive_message(message: Message) -> None:
    """尽量删除包含敏感 token 的用户消息；失败时不影响主流程。"""

    try:
        await message.delete()
    except TelegramAPIError:
        logger.warning("无法删除敏感消息: chat_id=%s message_id=%s", message.chat.id, message.message_id)


@manage_router.message(CommandStart())
async def start_command(message: Message, settings: Settings) -> None:
    """管理主 Bot 的入口。"""

    if message.from_user is None:
        return

    async with session_scope() as session:
        await ensure_user(session, message.from_user, settings)

    await message.answer(build_help_text(), reply_markup=build_master_menu())


@manage_router.message(Command("help"))
async def help_command(message: Message) -> None:
    """显示帮助。"""

    await message.answer(build_help_text(), reply_markup=build_master_menu())


async def send_createbot_link(
    message: Message,
    telegram_user,
    command_args: str,
    bot: Bot,
) -> None:
    """发送 Telegram 官方 Managed Bot 创建链接。"""

    manager = await bot.get_me()
    if getattr(manager, "can_manage_bots", None) is not True:
        await message.answer("当前主 Bot 没有 can_manage_bots=True，请先在 BotFather MiniApp 开启 Bot Management。")
        return

    args = command_args.split(maxsplit=1)
    suggested_username = args[0] if args else f"guest_{telegram_user.id}_bot"
    suggested_name = args[1] if len(args) > 1 else "Guest Clone Bot"
    if not suggested_username.lower().endswith("bot"):
        suggested_username = f"{suggested_username}_bot"

    create_link = (
        f"https://t.me/newbot/{manager.username}/{suggested_username}"
        f"?name={quote(suggested_name)}"
    )
    await message.answer(
        "点击下面链接创建受管理的租户 Bot。创建完成后，Telegram 会自动把结果发回这里：\n"
        f"{create_link}"
    )


async def send_owner_bots(message: Message, telegram_user, settings: Settings) -> None:
    """发送当前用户的租户 Bot 列表。"""

    async with session_scope() as session:
        owner = await ensure_user(session, telegram_user, settings)
        tenants = await list_owner_tenants(session, owner.id)

    if not tenants:
        await message.answer("你还没有绑定租户 Bot。使用 /createbot 或 /addtoken 开始。", reply_markup=build_master_menu())
        return

    lines = ["我的租户 Bot："]
    for tenant in tenants:
        status = "启用" if tenant.is_active else "停用"
        lines.append(
            f"#{tenant.id} @{tenant.username} {status} "
            f"source={tenant.token_source} guest={tenant.supports_guest_queries}"
        )
    await message.answer("\n".join(lines), reply_markup=build_owner_bots_keyboard(tenants))


@manage_router.message(Command("createbot"))
async def createbot_command(message: Message, command: CommandObject, bot: Bot) -> None:
    """生成 Telegram 官方 Managed Bot 创建链接。"""

    if message.from_user is None:
        return

    await send_createbot_link(message, message.from_user, command.args or "", bot)


@manage_router.callback_query(F.data == "master:createbot")
async def createbot_callback(callback: CallbackQuery, bot: Bot) -> None:
    """按钮：创建受管理 Bot。"""

    if callback.message is None or not isinstance(callback.message, Message):
        await callback.answer()
        return
    await send_createbot_link(callback.message, callback.from_user, "", bot)
    await callback.answer()


@manage_router.callback_query(F.data == "master:mybots")
async def mybots_callback(callback: CallbackQuery, settings: Settings) -> None:
    """按钮：查看我的租户 Bot。"""

    if callback.message is None or not isinstance(callback.message, Message):
        await callback.answer()
        return
    await send_owner_bots(callback.message, callback.from_user, settings)
    await callback.answer()


@manage_router.callback_query(F.data == "master:help")
async def help_callback(callback: CallbackQuery) -> None:
    """按钮：显示帮助。"""

    if callback.message and isinstance(callback.message, Message):
        await callback.message.answer(build_help_text(), reply_markup=build_master_menu())
    await callback.answer()


@manage_router.message(F.managed_bot_created)
async def managed_bot_created_message(
    message: Message,
    bot: Bot,
    settings: Settings,
    token_cipher: TokenCipher,
    tenant_manager,
) -> None:
    """用户通过 Telegram 官方流程创建 Managed Bot 后保存 token。"""

    if message.from_user is None or message.managed_bot_created is None:
        return

    bot_user = message.managed_bot_created.bot_user
    try:
        raw_token = await bot.get_managed_bot_token(user_id=bot_user.id)
    except TelegramAPIError as exc:
        logger.exception("获取 Managed Bot Token 失败: bot_id=%s", bot_user.id)
        await message.answer(f"获取受管理 Bot Token 失败：{exc}")
        return

    async with session_scope() as session:
        owner = await ensure_user(session, message.from_user, settings)
        tenant = await upsert_tenant_bot(
            session=session,
            owner=owner,
            bot_user=bot_user,
            raw_token=raw_token,
            cipher=token_cipher,
            token_source=TokenSource.MANAGED,
        )

    await tenant_manager.start_tenant_by_id(tenant.id)
    await message.answer(
        f"已绑定受管理 Bot：@{tenant.username}\n"
        "下一步：打开 https://t.me/Botfather?startapp ，选择该 Bot，进入 Bot Settings，"
        "打开 Guest Chat Mode。\n"
        f"随后直接打开 @{tenant.username} 发送 /start，可用按钮新增、编辑和测试模板。"
    )


@manage_router.managed_bot()
async def managed_bot_updated_event(event: ManagedBotUpdated) -> None:
    """记录 Managed Bot 变更事件。当前 MVP 只打日志。"""

    logger.info(
        "Managed Bot 更新: owner=%s bot=%s",
        event.user.id,
        event.bot_user.id,
    )


@manage_router.message(Command("addtoken"))
async def addtoken_command(
    message: Message,
    command: CommandObject,
    settings: Settings,
    token_cipher: TokenCipher,
    tenant_manager,
) -> None:
    """手动绑定已有 Bot Token，作为 Managed Bots 的兼容兜底。"""

    if message.from_user is None:
        return

    token = (command.args or "").strip()
    if not token:
        await message.answer("用法：/addtoken &lt;bot_token&gt;")
        return
    await delete_sensitive_message(message)

    try:
        bot_user = await validate_bot_token(token)
    except TenantTokenError as exc:
        await message.answer(str(exc))
        return

    async with session_scope() as session:
        owner = await ensure_user(session, message.from_user, settings)
        tenant = await upsert_tenant_bot(
            session=session,
            owner=owner,
            bot_user=bot_user,
            raw_token=token,
            cipher=token_cipher,
            token_source=TokenSource.MANUAL,
        )

    await tenant_manager.start_tenant_by_id(tenant.id)
    await message.answer(
        f"已绑定 @{tenant.username}。\n"
        f"supports_guest_queries={tenant.supports_guest_queries}\n"
        "如果不是 True，请打开 https://t.me/Botfather?startapp ，选择该 Bot，"
        "进入 Bot Settings，打开 Guest Chat Mode。"
    )


@manage_router.message(Command("mybots"))
async def mybots_command(message: Message, settings: Settings) -> None:
    """查看当前用户绑定的租户 Bot。"""

    if message.from_user is None:
        return

    await send_owner_bots(message, message.from_user, settings)


@manage_router.message(Command("refreshbot"))
async def refreshbot_command(
    message: Message,
    command: CommandObject,
    settings: Settings,
    token_cipher: TokenCipher,
    tenant_manager,
) -> None:
    """刷新租户 Bot 能力状态，并重启该租户 polling。"""

    if message.from_user is None:
        return

    bot_username = (command.args or "").strip()
    if not bot_username:
        await message.answer("用法：/refreshbot @bot")
        return

    async with session_scope() as session:
        owner = await ensure_user(session, message.from_user, settings)
        tenant = await get_tenant_by_username(session, owner.id, bot_username)
        if tenant is None:
            await message.answer("未找到该 Bot。")
            return
        raw_token = token_cipher.decrypt(tenant.encrypted_token)
        token_source = TokenSource(tenant.token_source)

    try:
        bot_user = await validate_bot_token(raw_token)
    except TenantTokenError as exc:
        await message.answer(f"刷新失败：{exc}")
        return

    async with session_scope() as session:
        owner = await ensure_user(session, message.from_user, settings)
        tenant = await upsert_tenant_bot(
            session=session,
            owner=owner,
            bot_user=bot_user,
            raw_token=raw_token,
            cipher=token_cipher,
            token_source=token_source,
        )

    await tenant_manager.stop_tenant(tenant.id)
    await tenant_manager.start_tenant_by_id(tenant.id)
    await message.answer(
        f"@{tenant.username} 状态已刷新并重启。\n"
        f"Guest Mode：{tenant.supports_guest_queries}\n"
        "如果仍不是 True：打开 https://t.me/Botfather?startapp → 选择该 Bot → "
        "Bot Settings → Guest Chat Mode → 打开。"
    )


@manage_router.message(Command("seedtemplates"))
async def seedtemplates_command(message: Message, command: CommandObject, settings: Settings) -> None:
    """为租户写入测试模板。"""

    if message.from_user is None:
        return

    bot_username = (command.args or "").strip()
    if not bot_username:
        await message.answer("用法：/seedtemplates @bot")
        return

    async with session_scope() as session:
        owner = await ensure_user(session, message.from_user, settings)
        tenant = await get_tenant_by_username(session, owner.id, bot_username)
        if tenant is None:
            await message.answer("未找到该 Bot。")
            return
        created_count = await seed_sample_templates(session, tenant.id)

    if created_count == 0:
        await message.answer("该 Bot 已有模板，未重复写入示例模板。")
        return
    await message.answer(f"已为 @{tenant.username} 写入 {created_count} 个测试模板：广告、推广、你好。")


@manage_router.message(Command("tenantstatus"))
async def tenantstatus_command(message: Message, command: CommandObject, settings: Settings) -> None:
    """查看单个租户 Bot 的状态。"""

    if message.from_user is None:
        return

    bot_username = (command.args or "").strip()
    if not bot_username:
        await message.answer("用法：/tenantstatus @bot")
        return

    async with session_scope() as session:
        owner = await ensure_user(session, message.from_user, settings)
        tenant = await get_tenant_by_username(session, owner.id, bot_username)
        if tenant is None:
            await message.answer("未找到该 Bot。")
            return
        templates = await list_templates(session, tenant.id, include_disabled=True)

    enabled_templates = sum(1 for template in templates if template.is_enabled)
    default_template = next((template for template in templates if template.is_default), None)
    await message.answer(
        f"租户状态：@{tenant.username}\n"
        f"ID：#{tenant.id}\n"
        f"状态：{'启用' if tenant.is_active else '停用'}\n"
        f"来源：{tenant.token_source}\n"
        f"Managed：{tenant.is_managed}\n"
        f"Guest 支持：{tenant.supports_guest_queries}\n"
        f"Inline 支持：{tenant.supports_inline_queries}\n"
        f"模板：{enabled_templates}/{len(templates)} 启用\n"
        f"默认模板：{default_template.id if default_template else '未设置'}\n"
        f"最后错误：{tenant.last_error or '无'}\n\n"
        f"刷新状态：/refreshbot @{tenant.username}\n"
        "如 Guest 支持不是 True：打开 https://t.me/Botfather?startapp → 选择该 Bot → "
        "Bot Settings → Guest Chat Mode → 打开。"
    )


@manage_router.message(Command("rotatetoken"))
async def rotatetoken_command(
    message: Message,
    command: CommandObject,
    bot: Bot,
    settings: Settings,
    token_cipher: TokenCipher,
    tenant_manager,
) -> None:
    """轮换 Managed Bot Token。"""

    if message.from_user is None:
        return

    bot_username = (command.args or "").strip()
    if not bot_username:
        await message.answer("用法：/rotatetoken @bot")
        return

    async with session_scope() as session:
        owner = await ensure_user(session, message.from_user, settings)
        tenant = await get_tenant_by_username(session, owner.id, bot_username)
        if tenant is None:
            await message.answer("未找到该 Bot。")
            return
        if not tenant.is_managed:
            await message.answer("只有通过 /createbot 创建的 Managed Bot 支持自动轮换 token。")
            return
        bot_user_id = tenant.bot_user_id

    try:
        raw_token = await bot.replace_managed_bot_token(user_id=bot_user_id)
        bot_user = await validate_bot_token(raw_token)
    except (TelegramAPIError, TenantTokenError) as exc:
        logger.exception("轮换 Managed Bot Token 失败: bot_id=%s", bot_user_id)
        await message.answer(f"轮换失败：{exc}")
        return

    async with session_scope() as session:
        owner = await ensure_user(session, message.from_user, settings)
        tenant = await upsert_tenant_bot(
            session=session,
            owner=owner,
            bot_user=bot_user,
            raw_token=raw_token,
            cipher=token_cipher,
            token_source=TokenSource.MANAGED,
        )

    await tenant_manager.stop_tenant(tenant.id)
    await tenant_manager.start_tenant_by_id(tenant.id)
    await message.answer(f"@{tenant.username} token 已轮换并重启。")


@manage_router.message(Command("addtemplate"))
async def addtemplate_command(message: Message, command: CommandObject, settings: Settings) -> None:
    """添加模板。"""

    if message.from_user is None:
        return

    payload = command.args or ""
    if not payload:
        await message.answer(
            "用法：\n"
            "/addtemplate @bot =广告 | 广告标题 | <b>广告文案</b> | https://image.jpg | "
            '[{"text":"联系","url":"https://example.com"}]\n\n'
            "关键词前缀：= 精确匹配，~ 模糊匹配；不写默认模糊匹配。\n"
            "图片 URL 和按钮 JSON 可省略。"
        )
        return

    try:
        parsed_payload = parse_template_command(payload)
    except TemplateParseError as exc:
        await message.answer(str(exc))
        return

    async with session_scope() as session:
        owner = await ensure_user(session, message.from_user, settings)
        tenant = await get_tenant_by_username(
            session,
            owner_user_id=owner.id,
            username=parsed_payload["bot_username"],
        )
        if tenant is None:
            await message.answer("未找到该 Bot，请先 /createbot 或 /addtoken。")
            return
        template = await create_template(session, tenant.id, parsed_payload)

    await message.answer(f"模板已添加：#{template.id} @{tenant.username} keyword={template.keyword}")


@manage_router.message(Command("mytemplates"))
async def mytemplates_command(message: Message, command: CommandObject, settings: Settings) -> None:
    """查看模板。"""

    if message.from_user is None:
        return

    bot_username = (command.args or "").strip()
    if not bot_username:
        await message.answer("用法：/mytemplates @bot")
        return

    async with session_scope() as session:
        owner = await ensure_user(session, message.from_user, settings)
        tenant = await get_tenant_by_username(session, owner.id, bot_username)
        if tenant is None:
            await message.answer("未找到该 Bot。")
            return
        templates = await list_templates(session, tenant.id, include_disabled=True)

    if not templates:
        await message.answer("暂无模板。")
        return

    lines = [
        f"@{tenant.username} 模板：",
        "说明：精确匹配=必须完全等于关键词；模糊匹配=输入里包含关键词就命中；默认=无命中时使用。",
        "",
    ]
    for template in templates[:50]:
        default_mark = " 默认" if template.is_default else ""
        enabled_mark = "启用" if template.is_enabled else "停用"
        mode_label = "精确匹配" if template.match_mode == "exact" else "模糊匹配"
        lines.append(
            f"#{template.id} [{mode_label}] {template.keyword} "
            f"{enabled_mark}{default_mark} - {template.title}"
        )
    await message.answer("\n".join(lines))


@manage_router.message(Command("deltemplate"))
async def deltemplate_command(message: Message, command: CommandObject, settings: Settings) -> None:
    """删除模板。"""

    if message.from_user is None:
        return

    template_id_text = (command.args or "").strip()
    if not template_id_text.isdigit():
        await message.answer("用法：/deltemplate &lt;template_id&gt;")
        return

    async with session_scope() as session:
        owner = await ensure_user(session, message.from_user, settings)
        tenants = await list_owner_tenants(session, owner.id)
        deleted = await delete_template(
            session,
            template_id=int(template_id_text),
            owner_tenant_ids={tenant.id for tenant in tenants},
        )

    await message.answer("模板已删除。" if deleted else "模板不存在或无权限。")


@manage_router.message(Command("edittemplate"))
async def edittemplate_command(message: Message, command: CommandObject, settings: Settings) -> None:
    """编辑模板字段。"""

    if message.from_user is None:
        return

    args = (command.args or "").split(maxsplit=2)
    if len(args) != 3 or not args[0].isdigit():
        await message.answer(
            "用法：/edittemplate &lt;template_id&gt; &lt;field&gt; &lt;value&gt;\n"
            "字段：keyword/mode/title/text/photo/buttons/weight/enabled\n"
            "清空 photo 或 buttons：值填 -"
        )
        return

    template_id = int(args[0])
    field_name = args[1]
    raw_value = args[2]

    try:
        async with session_scope() as session:
            owner = await ensure_user(session, message.from_user, settings)
            tenants = await list_owner_tenants(session, owner.id)
            updated = await update_template_field(
                session,
                template_id=template_id,
                owner_tenant_ids={tenant.id for tenant in tenants},
                field_name=field_name,
                raw_value=raw_value,
            )
    except TemplateParseError as exc:
        await message.answer(str(exc))
        return

    await message.answer("模板已更新。" if updated else "模板不存在或无权限。")


@manage_router.message(Command("setdefault"))
async def setdefault_command(message: Message, command: CommandObject, settings: Settings) -> None:
    """设置默认模板。"""

    if message.from_user is None:
        return

    template_id_text = (command.args or "").strip()
    if not template_id_text.isdigit():
        await message.answer("用法：/setdefault &lt;template_id&gt;")
        return

    async with session_scope() as session:
        owner = await ensure_user(session, message.from_user, settings)
        tenants = await list_owner_tenants(session, owner.id)
        updated = await set_default_template(
            session,
            template_id=int(template_id_text),
            owner_tenant_ids={tenant.id for tenant in tenants},
        )

    await message.answer("默认模板已更新。" if updated else "模板不存在或无权限。")
