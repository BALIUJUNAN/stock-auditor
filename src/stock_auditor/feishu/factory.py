"""按 ``feishu.yaml`` 与环境变量创建通道；任何缺失都降级为未配置。"""

from __future__ import annotations

import os

from stock_auditor.feishu.app_bot import AppBotChannel
from stock_auditor.feishu.base import FeishuChannel, UnconfiguredChannel
from stock_auditor.feishu.config import load_feishu_config
from stock_auditor.feishu.webhook import WebhookChannel


def create_feishu_channel() -> FeishuChannel:
    config = load_feishu_config()
    if config is None:
        return UnconfiguredChannel("缺少 config/local/feishu.yaml")
    if config.channel == "app":
        return AppBotChannel(
            app_id=os.environ.get("FEISHU_APP_ID", ""),
            app_secret=os.environ.get("FEISHU_APP_SECRET", ""),
            chat_id=config.chat_id,
        )
    return WebhookChannel(
        url=os.environ.get("FEISHU_WEBHOOK_URL", ""),
        secret=os.environ.get("FEISHU_WEBHOOK_SECRET", ""),
    )
