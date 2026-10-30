"""``sa doctor --send-test`` 使用的最小卡片（飞书卡片 JSON 2.0）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def build_test_card(channel: str, now: datetime | None = None) -> dict[str, Any]:
    sent_at = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": "选股审计系统 · 通道测试"},
            "template": "blue",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        "**飞书通道连接正常**\n\n"
                        f"- 通道：{channel}\n"
                        f"- 发送时间：{sent_at}"
                    ),
                }
            ]
        },
    }
