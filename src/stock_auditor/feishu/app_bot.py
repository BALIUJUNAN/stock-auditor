"""自建应用机器人通道；``lark-oapi`` 延迟导入，避免拖慢所有命令。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from stock_auditor.feishu.base import FeishuChannel, FeishuError

log = structlog.get_logger(__name__)


class AppBotChannel(FeishuChannel):
    name = "app"

    def __init__(self, app_id: str, app_secret: str, chat_id: str) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._chat_id = chat_id
        self._client: Any = None

    @property
    def configured(self) -> bool:
        return bool(self._app_id and self._app_secret and self._chat_id)

    @property
    def status(self) -> str:
        if not self._app_id or not self._app_secret:
            return "未配置：缺少 FEISHU_APP_ID/FEISHU_APP_SECRET"
        if not self._chat_id:
            return "未配置：feishu.yaml 缺少 chat_id"
        return "已配置"

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        import lark_oapi as lark

        self._client = (
            lark.Client.builder()
            .app_id(self._app_id)
            .app_secret(self._app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )
        return self._client

    def send_card(self, card: dict[str, Any]) -> str:
        if not self.configured:
            raise FeishuError(self.status)
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        client = self._ensure_client()
        body = (
            CreateMessageRequestBody.builder()
            .receive_id(self._chat_id)
            .msg_type("interactive")
            .content(json.dumps(card, ensure_ascii=False))
            .build()
        )
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(body)
            .build()
        )
        response = client.im.v1.message.create(request)
        if not response.success():
            raise FeishuError(
                f"飞书发送失败 code={response.code} msg={response.msg}"
            )
        message_id = str(response.data.message_id or "")
        log.info("feishu.app.sent", message_id=message_id)
        return message_id

    def upload_image(self, path: Path) -> str | None:
        if not self.configured:
            raise FeishuError(self.status)
        from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody

        client = self._ensure_client()
        with path.open("rb") as image:
            body = (
                CreateImageRequestBody.builder()
                .image_type("message")
                .image(image)
                .build()
            )
            request = CreateImageRequest.builder().request_body(body).build()
            response = client.im.v1.image.create(request)
        if not response.success():
            raise FeishuError(
                f"飞书图片上传失败 code={response.code} msg={response.msg}"
            )
        image_key = str(response.data.image_key or "")
        log.info("feishu.app.image_uploaded", image_key=image_key)
        return image_key or None
