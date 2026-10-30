"""群自定义机器人 Webhook 通道（备用，仅发送）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Any

import httpx
import structlog

from stock_auditor.feishu.base import FeishuChannel, FeishuError

log = structlog.get_logger(__name__)


def webhook_signature(timestamp: str, secret: str) -> str:
    """飞书自定义机器人签名：HMAC-SHA256(key="timestamp\\nsecret", data="")。"""
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


class WebhookChannel(FeishuChannel):
    name = "webhook"

    def __init__(self, url: str, secret: str = "") -> None:
        self._url = url
        self._secret = secret

    @property
    def configured(self) -> bool:
        return bool(self._url)

    @property
    def status(self) -> str:
        return "已配置" if self.configured else "未配置：缺少 FEISHU_WEBHOOK_URL"

    def send_card(self, card: dict[str, Any]) -> str:
        if not self.configured:
            raise FeishuError(self.status)
        payload: dict[str, Any] = {"msg_type": "interactive", "card": card}
        if self._secret:
            timestamp = str(int(time.time()))
            payload["timestamp"] = timestamp
            payload["sign"] = webhook_signature(timestamp, self._secret)
        try:
            response = httpx.post(self._url, json=payload, timeout=30)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise FeishuError(f"飞书 Webhook 网络或 HTTP 错误: {type(exc).__name__}") from exc
        except ValueError as exc:
            raise FeishuError("飞书 Webhook 返回无效 JSON") from exc
        if not isinstance(body, dict):
            raise FeishuError("飞书 Webhook 返回无效响应")
        if body.get("code") != 0:
            raise FeishuError(
                f"飞书 Webhook 返回错误 code={body.get('code')} msg={body.get('msg')}"
            )
        message_id = str((body.get("data") or {}).get("message_id") or "")
        log.info("feishu.webhook.sent", message_id=message_id)
        return message_id
