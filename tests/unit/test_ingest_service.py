from __future__ import annotations

import duckdb

from stock_auditor.config import load_settings
from stock_auditor.db import apply_migrations
from stock_auditor.ingest import service
from stock_auditor.ingest.common import DataClient


def test_per_stock_failure_propagates_to_ingest_summary(monkeypatch):
    settings = load_settings()
    client = DataClient(settings)
    monkeypatch.setattr(service.universe, "collect_universe", lambda *args: [])
    monkeypatch.setattr(service.universe, "store_universe", lambda *args: 0)
    monkeypatch.setattr(service, "_needs_industry", lambda *args: False)

    def quotes(client, settings, codes):
        client.record_failure("quotes", "000001", RuntimeError("offline"))
        return []

    monkeypatch.setattr(service.quotes, "collect_quotes", quotes)
    for module, function in (
        (service.financials, "collect_financials"),
        (service.valuation, "collect_valuation"),
        (service.announcements, "collect_announcements"),
        (service.research, "collect_research"),
        (service.earnings, "collect_earnings"),
        (service.index, "collect_index"),
    ):
        monkeypatch.setattr(module, function, lambda *args: [])
    monkeypatch.setattr(service.announcements, "backfill_announcement_text", lambda *args: (0, {}))
    with duckdb.connect(":memory:") as db:
        apply_migrations(db)
        db.execute("INSERT INTO stock_universe (code, name) VALUES ('000001', 'test')")
        summary = service.run_ingest(db, settings, client=client)
    assert summary.failed_codes["quotes"] == {"000001": "offline"}
    assert "quotes" in summary.errors
    assert summary.successful_codes["quotes"] == 0
    assert summary.status == "failed"
