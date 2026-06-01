from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def main() -> None:
    """离线 smoke 检查，不调用 Telegram API。"""

    temp_dir = tempfile.TemporaryDirectory()
    os.environ.setdefault("MASTER_BOT_TOKEN", "123456:TEST_TOKEN")
    os.environ["FERNET_KEY"] = Fernet.generate_key().decode()
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{temp_dir.name}/smoke.db"

    from database import close_db, init_db, session_scope
    from models.template import MatchMode
    from models.tenant_bot import TenantBot, TokenSource
    from models.user import User
    from services.inline_result_service import build_inline_results
    from services.template_service import (
        TemplateParseError,
        create_template,
        get_template,
        match_templates,
        parse_template_command,
        toggle_template_enabled,
        update_template_field,
    )
    from handlers.guest import normalize_guest_query
    from utils.crypto import TokenCipher
    from utils.text_format import markdown_links_to_html

    await init_db()
    assert normalize_guest_query("@tenant_bot 广告", "tenant_bot") == "广告"
    assert normalize_guest_query("@Tenant_Bot   推广", "tenant_bot") == "推广"
    assert (
        markdown_links_to_html("限时免费搜索 [点击进入](https://t.me/kuai?start=a_ATC98L)")
        == '限时免费搜索 <a href="https://t.me/kuai?start=a_ATC98L">点击进入</a>'
    )

    cipher = TokenCipher(os.environ["FERNET_KEY"])
    encrypted_token = cipher.encrypt("123456:ABC")
    assert cipher.decrypt(encrypted_token) == "123456:ABC"

    async with session_scope() as session:
        user = User(telegram_id=1, username="owner", first_name="Owner", is_admin=True)
        session.add(user)
        await session.flush()

        tenant = TenantBot(
            owner_user_id=user.id,
            bot_user_id=10001,
            username="tenant_bot",
            first_name="Tenant",
            encrypted_token=encrypted_token,
            token_source=TokenSource.MANUAL.value,
            is_managed=False,
            is_active=True,
            supports_inline_queries=True,
            supports_guest_queries=False,
            last_error=None,
        )
        session.add(tenant)
        await session.flush()

        payload = parse_template_command(
            '@tenant_bot =广告 | 广告标题 | <b>广告文案</b> | '
            'https://example.com/a.jpg | [{"text":"联系","url":"https://example.com"}]'
        )
        template = await create_template(session, tenant.id, payload)
        assert await get_template(session, template.id, {tenant.id}) is not None
        matched = await match_templates(session, tenant.id, "广告")
        assert len(matched) == 1
        assert matched[0].match_mode == MatchMode.EXACT.value

        results = build_inline_results(matched, "广告")
        assert len(results) == 1

        updated = await update_template_field(
            session,
            template_id=template.id,
            owner_tenant_ids={tenant.id},
            field_name="weight",
            raw_value="5",
        )
        assert updated is True
        assert template.weight == 5

        try:
            await update_template_field(
                session,
                template_id=template.id,
                owner_tenant_ids={tenant.id},
                field_name="photo",
                raw_value="http://example.com/a.jpg",
            )
        except TemplateParseError as exc:
            assert "图片 URL" in str(exc)
        else:
            raise AssertionError("非 HTTPS 图片 URL 应被拒绝")

        toggled = await toggle_template_enabled(session, template.id, {tenant.id})
        assert toggled is not None
        assert toggled.is_enabled is False

    await close_db()
    temp_dir.cleanup()
    print("smoke_check_ok")


if __name__ == "__main__":
    asyncio.run(main())
