from __future__ import annotations

import logging


def setup_logging(log_level: str) -> None:
    """初始化应用日志。Docker 下直接输出到 stdout。"""

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
