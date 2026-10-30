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
