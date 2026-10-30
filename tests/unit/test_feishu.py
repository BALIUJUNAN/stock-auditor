from __future__ import annotations

from datetime import datetime

import pytest

from stock_auditor.feishu import (
    FeishuConfig,
    FeishuError,
    UnconfiguredChannel,
    build_test_card,
    create_feishu_channel,
)
from stock_auditor.feishu.app_bot import AppBotChannel
from stock_auditor.feishu.webhook import WebhookChannel, webhook_signature


def test_webhook_signature_matches_known_vector() -> None:
    assert (
        webhook_signature("1700000000", "test-secret")
        == "mbm4Y4oluIPQ00qlBIhX8vAZ0EKv3nw0LuTb91jPL84="
    )


def test_unconfigured_channel_raises() -> None:
    channel = UnconfiguredChannel()
    assert channel.configured is False
    assert "未配置" in channel.status
    with pytest.raises(FeishuError):
        channel.send_card({})


def test_test_card_is_json_2() -> None:
    card = build_test_card("app", now=datetime(2026, 10, 30, 9, 30, 0))
    assert card["schema"] == "2.0"
    content = card["body"]["elements"][0]["content"]
    assert "app" in content
    assert "2026-10-30 09:30:00" in content


def test_factory_without_config_is_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("stock_auditor.feishu.factory.load_feishu_config", lambda: None)
    channel = create_feishu_channel()
    assert isinstance(channel, UnconfiguredChannel)
    assert "未配置" in channel.status


def test_factory_webhook_requires_url(monkeypatch: pytest.MonkeyPatch) -> None:
    config = FeishuConfig(channel="webhook")
    monkeypatch.setattr(
        "stock_auditor.feishu.factory.load_feishu_config", lambda: config
    )
    monkeypatch.delenv("FEISHU_WEBHOOK_URL", raising=False)
    channel = create_feishu_channel()
    assert isinstance(channel, WebhookChannel)
    assert channel.configured is False

    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "https://example.invalid/hook")
    channel = create_feishu_channel()
    assert channel.configured is True


def test_factory_app_requires_chat_id(monkeypatch: pytest.MonkeyPatch) -> None:
    config = FeishuConfig(channel="app", chat_id="")
    monkeypatch.setattr(
        "stock_auditor.feishu.factory.load_feishu_config", lambda: config
    )
    monkeypatch.setenv("FEISHU_APP_ID", "app-id")
    monkeypatch.setenv("FEISHU_APP_SECRET", "app-secret")
    channel = create_feishu_channel()
    assert isinstance(channel, AppBotChannel)
    assert channel.configured is False
    assert "chat_id" in channel.status
