"""飞书推送通道。"""

from __future__ import annotations

import importlib
from typing import Any

from stock_auditor.feishu.base import FeishuChannel, FeishuError, UnconfiguredChannel
from stock_auditor.feishu.config import FeishuConfig, load_feishu_config
from stock_auditor.feishu.factory import create_feishu_channel
from stock_auditor.feishu.ignored import (
    ignore_code,
    ignored_codes,
    is_ignored,
    week_key,
)
from stock_auditor.feishu.test_card import build_test_card

# 指令与长连接依赖 pipeline/report，延迟到首次访问，避免导入期循环。
_LAZY_EXPORTS = {
    "ALERT_BUTTONS": "stock_auditor.feishu.actions",
    "BUTTON_IGNORE": "stock_auditor.feishu.actions",
    "BUTTON_WATCH": "stock_auditor.feishu.actions",
    "CommandService": "stock_auditor.feishu.commands",
    "run_bot": "stock_auditor.feishu.bot",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value

__all__ = [
    "ALERT_BUTTONS",
    "BUTTON_IGNORE",
    "BUTTON_WATCH",
    "CommandService",
    "FeishuChannel",
    "FeishuConfig",
    "FeishuError",
    "UnconfiguredChannel",
    "build_test_card",
    "create_feishu_channel",
    "ignore_code",
    "ignored_codes",
    "is_ignored",
    "load_feishu_config",
    "run_bot",
    "week_key",
]
