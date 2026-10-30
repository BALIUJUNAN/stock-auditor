"""周报得分图渲染与飞书图片上传。"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from stock_auditor.feishu.app_bot import AppBotChannel
from stock_auditor.feishu.base import FeishuError
from stock_auditor.feishu.webhook import WebhookChannel
from stock_auditor.report import build_main_card
from stock_auditor.report.charts import render_weekly_chart

PAYLOAD = {
    "run_id": "weekly-20261029-200000",
    "as_of": "2026-10-29",
    "audit_skipped": False,
    "top": [
        {
            "code": "000001",
            "name": "测试甲",
            "final_total": 80.0,
            "quant_total": 50.0,
        },
        {
            "code": "000002",
            "name": "测试乙",
            "final_total": 65.5,
            "quant_total": 55.0,
        },
    ],
}

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_render_weekly_chart_writes_png(tmp_path: Path) -> None:
    output = tmp_path / "chart.png"
    result = render_weekly_chart(PAYLOAD, output)

    assert result == output
    assert output.read_bytes()[:8] == PNG_MAGIC
    assert output.stat().st_size > 1000


def test_render_weekly_chart_falls_back_to_quant_score(tmp_path: Path) -> None:
    payload = {
        "as_of": "2026-10-29",
        "top": [{"code": "000001", "name": "测试甲", "quant_total": 42.0}],
    }
    output = tmp_path / "chart.png"
    assert render_weekly_chart(payload, output) == output
    assert output.exists()


def test_render_weekly_chart_skips_empty_top(tmp_path: Path) -> None:
    output = tmp_path / "chart.png"
    assert render_weekly_chart({"as_of": "2026-10-29", "top": []}, output) is None
    assert not output.exists()


def test_main_card_embeds_image_when_uploaded() -> None:
    card = build_main_card(
        {
            "as_of": "2026-10-29",
            "main_markdown": "1. **测试甲（000001）** ★★★★ 80 分",
            "report_url": "file:///tmp/weekly.md",
            "footer": "完整周报：/tmp/weekly.md",
        },
        image_key="img_abc",
    )
    elements = card["body"]["elements"]
    image = next(item for item in elements if item.get("tag") == "img")
    assert image["img_key"] == "img_abc"
    assert image["alt"]["content"] == "周报得分图"


def test_webhook_channel_has_no_image_upload(tmp_path: Path) -> None:
    channel = WebhookChannel("https://example.invalid/hook")
    assert channel.upload_image(tmp_path / "chart.png") is None


class _FakeResponse:
    code = 0
    msg = "ok"

    def __init__(self, image_key: str = "img_123") -> None:
        self.data = types.SimpleNamespace(image_key=image_key)

    def success(self) -> bool:
        return True


class _FailResponse:
    code = 99991
    msg = "上传失败"
    data = None

    def success(self) -> bool:
        return False


def _fake_client(response: object) -> types.SimpleNamespace:
    class _ImageApi:
        def create(self, request: object) -> object:
            captured["request"] = request
            return response

    captured: dict[str, object] = {}
    client = types.SimpleNamespace(
        im=types.SimpleNamespace(v1=types.SimpleNamespace(image=_ImageApi()))
    )
    client.captured = captured  # type: ignore[attr-defined]
    return client


def test_app_bot_upload_image_uses_lark_image_api(tmp_path: Path) -> None:
    channel = AppBotChannel("app-id", "app-secret", "chat-id")
    client = _fake_client(_FakeResponse())
    channel._client = client

    image = tmp_path / "chart.png"
    image.write_bytes(PNG_MAGIC + b"fake")

    assert channel.upload_image(image) == "img_123"
    request = client.captured["request"]
    body = request.request_body
    assert body.image_type == "message"
    assert body.image is not None


def test_app_bot_upload_image_raises_on_failure(tmp_path: Path) -> None:
    channel = AppBotChannel("app-id", "app-secret", "chat-id")
    channel._client = _fake_client(_FailResponse())

    image = tmp_path / "chart.png"
    image.write_bytes(PNG_MAGIC + b"fake")

    with pytest.raises(FeishuError, match="图片上传失败"):
        channel.upload_image(image)
