"""structlog 日志配置：JSON 输出到终端与 ``var/logs/``。"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import structlog
from structlog.types import Processor

from stock_auditor import paths

LOG_FILENAME = "stock-auditor.log"


def configure_logging(level: str | None = None, log_file: Path | None = None) -> None:
    """配置结构化日志。

    级别取参数、``SA_LOG_LEVEL`` 或默认 INFO；文件默认写入
    ``var/logs/stock-auditor.log``。重复调用会重置 handler，不会重复输出。
    """
    resolved_level = (level or os.environ.get("SA_LOG_LEVEL", "INFO")).upper()
    numeric_level = getattr(logging, resolved_level, logging.INFO)

    target = Path(log_file) if log_file is not None else paths.logs_dir() / LOG_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(ensure_ascii=False),
        foreign_pre_chain=shared_processors,
    )

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(target, encoding="utf-8"),
    ]
    root = logging.getLogger()
    root.handlers.clear()
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(numeric_level)
