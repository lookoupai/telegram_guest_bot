from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """配置错误，启动前必须修复。"""


def _parse_admin_ids(raw_value: str | None) -> frozenset[int]:
    """解析逗号分隔的管理员 Telegram ID。"""

    if not raw_value:
        return frozenset()

    admin_ids: set[int] = set()
    for item in raw_value.split(","):
        item = item.strip()
        if not item:
            continue
        admin_ids.add(int(item))
    return frozenset(admin_ids)


@dataclass(frozen=True)
class Settings:
    """应用配置。

    Docker 化后只需要把这些环境变量注入容器即可；SQLite 文件建议挂载到 /data。
    """

    master_bot_token: str
    fernet_key: str
    database_url: str
    admin_ids: frozenset[int]
    log_level: str
    delete_webhook_on_start: bool

    @property
    def sqlite_file_path(self) -> Path | None:
        """从 SQLite URL 中提取本地文件路径，便于启动时创建目录。"""

        prefix = "sqlite+aiosqlite:///"
        if not self.database_url.startswith(prefix):
            return None

        raw_path = self.database_url.removeprefix(prefix)
        if raw_path.startswith("/"):
            return Path(raw_path)
        return Path(raw_path).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """读取 .env 和环境变量，返回不可变配置对象。"""

    load_dotenv()

    master_bot_token = os.getenv("MASTER_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    if not master_bot_token:
        raise ConfigError("缺少 MASTER_BOT_TOKEN。兼容旧配置时也可以继续使用 BOT_TOKEN。")

    fernet_key = os.getenv("FERNET_KEY")
    if not fernet_key:
        raise ConfigError(
            "缺少 FERNET_KEY。生成命令：python -c "
            "\"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )

    return Settings(
        master_bot_token=master_bot_token,
        fernet_key=fernet_key,
        database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/guest_bot.db"),
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        delete_webhook_on_start=os.getenv("DELETE_WEBHOOK_ON_START", "true").lower()
        in {"1", "true", "yes", "on"},
    )
