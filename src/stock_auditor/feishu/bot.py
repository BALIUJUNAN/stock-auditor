"""飞书自建应用长连接：接收消息与卡片按钮回调，交给 ``CommandService``。

``lark-oapi`` 延迟导入；长连接由 SDK 握手，不需要公网回调地址。
"""

from __future__ import annotations

import json
from collections import deque
from typing import Any

import structlog

from stock_auditor.feishu.commands import CommandService

log = structlog.get_logger(__name__)

_SEEN_LIMIT = 500


def _nested(obj: Any, *names: str, default: Any = None) -> Any:
    current = obj
    for name in names:
        current = getattr(current, name, None)
        if current is None:
            return default
    return current


def _build_client(lark: Any, app_id: str, app_secret: str) -> Any:
    return (
        lark.Client.builder()
        .app_id(app_id)
        .app_secret(app_secret)
        .log_level(lark.LogLevel.WARNING)
        .build()
    )


def _send_card(client: Any, chat_id: str, card: dict[str, Any]) -> str:
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

    body = (
        CreateMessageRequestBody.builder()
        .receive_id(chat_id)
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
        raise RuntimeError(f"飞书发送失败 code={response.code} msg={response.msg}")
    return str(_nested(response, "data", "message_id", default="") or "")


def _on_message(
    service: CommandService,
    client: Any,
    seen: deque[str],
    event: Any,
) -> None:
    data = getattr(event, "event", None)
    message = getattr(data, "message", None)
    if message is None:
        return
    message_id = str(getattr(message, "message_id", "") or "")
    if message_id:
        if message_id in seen:
            return
        seen.append(message_id)
    if getattr(message, "message_type", "") != "text":
        return
    try:
        content = json.loads(getattr(message, "content", "") or "{}")
    except json.JSONDecodeError:
        return
    if not isinstance(content, dict):
        return
    text = str(content.get("text", ""))
    chat_id = str(getattr(message, "chat_id", "") or "")
    user_id = str(_nested(data, "sender", "sender_id", "open_id", default="") or "")
    card = service.handle_text(text, chat_id=chat_id, user_id=user_id)
    if card is None:
        return
    _send_card(client, chat_id, card)


def _on_card_action(
    service: CommandService,
    client: Any,
    event: Any,
) -> Any:
    data = getattr(event, "event", None)
    value = getattr(getattr(data, "action", None), "value", None)
    if not isinstance(value, dict):
        value = {}
    user_id = str(_nested(data, "operator", "open_id", default="") or "")
    chat_id = str(_nested(data, "context", "open_chat_id", default="") or "")
    card = service.handle_action(
        str(value.get("action", "")),
        str(value.get("code", "")),
        chat_id=chat_id,
        user_id=user_id,
    )
    if card is not None:
        _send_card(client, chat_id, card)
    try:
        from lark_oapi.api.im.v1 import P2CardActionTriggerResponse

        toast = "已处理" if card is not None else "无权限或操作无效"
        return (
            P2CardActionTriggerResponse.builder()
            .toast({"type": "success", "content": toast})
            .build()
        )
    except Exception:  # pragma: no cover - SDK 版本差异
        return None


def run_bot(
    service: CommandService,
    *,
    app_id: str,
    app_secret: str,
    log_level: str = "warning",
) -> None:
    """阻塞运行长连接，直到进程收到退出信号。"""
    import lark_oapi as lark

    client = _build_client(lark, app_id, app_secret)
    seen: deque[str] = deque(maxlen=_SEEN_LIMIT)
    level = getattr(lark.LogLevel, log_level.upper(), lark.LogLevel.WARNING)

    def on_message(event: Any) -> None:
        try:
            _on_message(service, client, seen, event)
        except Exception:
            log.exception("feishu.bot.message_failed")

    def on_card_action(event: Any) -> Any:
        try:
            return _on_card_action(service, client, event)
        except Exception:
            log.exception("feishu.bot.action_failed")
            return None

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .register_p2_card_action_trigger(on_card_action)
        .build()
    )
    ws_client = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=handler,
        log_level=level,
    )
    log.info("feishu.bot.starting")
    ws_client.start()
