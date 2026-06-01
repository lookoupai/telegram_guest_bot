"""initial schema

Revision ID: 20260531_0001
Revises:
Create Date: 2026-05-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260531_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建初始表。"""

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_id"),
    )
    op.create_index(op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=True)

    op.create_table(
        "tenant_bots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("bot_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("token_source", sa.String(length=32), nullable=False),
        sa.Column("is_managed", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("supports_inline_queries", sa.Boolean(), nullable=True),
        sa.Column("supports_guest_queries", sa.Boolean(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_user_id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index(op.f("ix_tenant_bots_bot_user_id"), "tenant_bots", ["bot_user_id"], unique=True)
    op.create_index(op.f("ix_tenant_bots_owner_user_id"), "tenant_bots", ["owner_user_id"], unique=False)
    op.create_index(op.f("ix_tenant_bots_username"), "tenant_bots", ["username"], unique=True)

    op.create_table(
        "templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(length=255), nullable=False),
        sa.Column("match_mode", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("photo_url", sa.Text(), nullable=True),
        sa.Column("buttons_json", sa.JSON(), nullable=True),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant_bots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_templates_keyword"), "templates", ["keyword"], unique=False)
    op.create_index(op.f("ix_templates_tenant_id"), "templates", ["tenant_id"], unique=False)


def downgrade() -> None:
    """删除初始表。"""

    op.drop_index(op.f("ix_templates_tenant_id"), table_name="templates")
    op.drop_index(op.f("ix_templates_keyword"), table_name="templates")
    op.drop_table("templates")
    op.drop_index(op.f("ix_tenant_bots_username"), table_name="tenant_bots")
    op.drop_index(op.f("ix_tenant_bots_owner_user_id"), table_name="tenant_bots")
    op.drop_index(op.f("ix_tenant_bots_bot_user_id"), table_name="tenant_bots")
    op.drop_table("tenant_bots")
    op.drop_index(op.f("ix_users_telegram_id"), table_name="users")
    op.drop_table("users")
