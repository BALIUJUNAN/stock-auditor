"""告警卡片按钮与回调动作名（指令层与流水线共用）。"""

from __future__ import annotations

BUTTON_WATCH = "watch"
BUTTON_IGNORE = "ignore"
ALERT_BUTTONS: tuple[dict[str, str], ...] = (
    {"label": "加入关注", "action": BUTTON_WATCH},
    {"label": "本周忽略", "action": BUTTON_IGNORE},
)

__all__ = ["ALERT_BUTTONS", "BUTTON_IGNORE", "BUTTON_WATCH"]
