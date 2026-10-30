from __future__ import annotations

import duckdb

from stock_auditor.feishu.base import FeishuError
from stock_auditor.pipeline.outbox import deliver, enqueue


def test_failed_delivery_survives_restart_and_is_retried(tmp_path):
    path = str(tmp_path / "outbox.duckdb")

    class Channel:
        configured = True
        fail = True
        received = []

        def send_card(self, card):
            if self.fail:
                raise FeishuError("offline")
            self.received.append(card)

    channel = Channel()
    with duckdb.connect(path) as db:
        enqueue(db, {"text": "alert"}, key="event:1")
        assert deliver(db, channel) == 0
        assert db.execute("SELECT status, attempts FROM alert_outbox").fetchone() == ("pending", 1)
    channel.fail = False
    with duckdb.connect(path) as db:
        enqueue(db, {"text": "alert"}, key="event:1")
        assert deliver(db, channel) == 1
        assert deliver(db, channel) == 0
        assert db.execute("SELECT status, attempts FROM alert_outbox").fetchone() == ("sent", 2)
    assert channel.received == [{"text": "alert"}]


def test_webhook_timeout_and_http_errors_remain_pending(monkeypatch):
    import httpx

    from stock_auditor.feishu.webhook import WebhookChannel

    errors = [
        httpx.ConnectError("private url"),
        httpx.ReadTimeout("private url"),
        httpx.HTTPStatusError(
            "private url",
            request=httpx.Request("POST", "https://example.invalid"),
            response=httpx.Response(503),
        ),
    ]
    channel = WebhookChannel("https://example.invalid/private-token")
    for index, error in enumerate(errors):
        with duckdb.connect(":memory:") as db:
            enqueue(db, {"text": "alert"}, key=f"event:{index}")

            def fail(*args, _error=error, **kwargs):
                raise _error

            monkeypatch.setattr(httpx, "post", fail)
            assert deliver(db, channel) == 0
            status, attempts, message = db.execute(
                "SELECT status,attempts,error FROM alert_outbox"
            ).fetchone()
            assert status == "pending" and attempts == 1
            assert "private" not in message
