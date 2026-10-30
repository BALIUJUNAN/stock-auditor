from __future__ import annotations

from datetime import date

import pytest

from stock_auditor.ingest.announcements import announcement_id
from stock_auditor.ingest.earnings import period_label, recent_quarter_ends
from stock_auditor.ingest.index import index_symbol
from stock_auditor.ingest.pledge import candidate_snapshot_dates, snapshot_date
from stock_auditor.ingest.universe import board_from_code, is_st_name


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("600000", "sh_main"),
        ("688001", "star"),
        ("000001", "sz_main"),
        ("002773", "sz_main"),
        ("300750", "chinext"),
        ("301029", "chinext"),
        ("920000", "bse"),
        ("830799", "bse"),
    ],
)
def test_board_from_code(code: str, expected: str) -> None:
    assert board_from_code(code) == expected


def test_is_st_name() -> None:
    keywords = ["ST", "*ST", "退"]
    assert is_st_name("*ST天马", keywords)
    assert is_st_name("ST中珠", keywords)
    assert is_st_name("退市美都", keywords)
    assert not is_st_name("平安银行", keywords)


def test_snapshot_date_always_previous_friday() -> None:
    # 2026-10-29 是周四，最近已发布快照为 10-23 周五。
    assert snapshot_date(date(2026, 10, 29)) == date(2026, 10, 23)
    # 周五当天也回退一周，避免取到尚未更新的快照。
    assert snapshot_date(date(2026, 10, 23)) == date(2026, 10, 16)
    # 周六回退到本周五。
    assert snapshot_date(date(2026, 10, 24)) == date(2026, 10, 23)


def test_candidate_snapshot_dates_respects_lookback() -> None:
    candidates = candidate_snapshot_dates(date(2026, 10, 29), 21)
    assert candidates == [
        date(2026, 10, 23),
        date(2026, 10, 16),
        date(2026, 10, 9),
    ]


def test_recent_quarter_ends() -> None:
    assert recent_quarter_ends(date(2026, 10, 29)) == [
        date(2026, 9, 30),
        date(2026, 6, 30),
        date(2026, 3, 31),
        date(2025, 12, 31),
    ]
    assert recent_quarter_ends(date(2026, 1, 5)) == [
        date(2025, 12, 31),
        date(2025, 9, 30),
        date(2025, 6, 30),
        date(2025, 3, 31),
    ]


def test_period_label() -> None:
    assert period_label(date(2026, 9, 30)) == "2026三季"
    assert period_label(date(2025, 12, 31)) == "2025年报"
    assert period_label(date(2026, 6, 30)) == "2026半年报"
    assert period_label(date(2026, 3, 31)) == "2026一季"


def test_announcement_id_prefers_exchange_code() -> None:
    url = "https://data.eastmoney.com/notices/detail/002773/AN202610271831025817.html"
    assert announcement_id(url, "002773", date(2026, 10, 28), "公告") == "AN202610271831025817"


def test_announcement_id_fallback_is_stable() -> None:
    first = announcement_id(None, "002773", date(2026, 10, 28), "公告标题")
    second = announcement_id(None, "002773", date(2026, 10, 28), "公告标题")
    other = announcement_id(None, "002773", date(2026, 10, 29), "公告标题")
    assert first == second
    assert first != other
    assert first.startswith("002773-")


def test_index_symbol() -> None:
    assert index_symbol("000300") == "sh000300"
    assert index_symbol("399006") == "sz399006"


def test_announcement_text_backfill_retries_and_keeps_existing(monkeypatch):
    import duckdb

    from stock_auditor.db import apply_migrations
    from stock_auditor.ingest import announcements

    class Client:
        def call(self, func, *, description):
            return func()

    calls = []

    def fetch(ann_id):
        calls.append(ann_id)
        if len(calls) == 1:
            raise ValueError("offline")
        return "公告正文" * 40

    monkeypatch.setattr(announcements, "fetch_pdf_text", fetch)
    with duckdb.connect(":memory:") as db:
        apply_migrations(db)
        db.execute(
            "INSERT INTO announcements (ann_id, code, ann_date) "
            "VALUES ('AN123', '000001', DATE '2026-01-01')"
        )
        count, errors = announcements.backfill_announcement_text(db, Client())
        assert count == 0 and "AN123" in errors
        count, errors = announcements.backfill_announcement_text(db, Client())
        assert count == 1 and not errors
        text, digest = db.execute("SELECT text, text_hash FROM announcements").fetchone()
        assert len(text) >= 100 and len(digest) == 64
        announcements.store_announcements(
            db, [("AN123", "000001", date(2026, 1, 1), "title", None, None, None, None)]
        )
        assert db.execute("SELECT text FROM announcements").fetchone()[0] == text


def test_pdf_download_extracts_text(monkeypatch):
    from stock_auditor.ingest import announcements

    sentence = "Verified disclosure evidence " * 8
    stream = f"BT /F1 10 Tf 20 700 Td ({sentence}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, size):
            yield bytes(data)

    monkeypatch.setattr(announcements.requests, "get", lambda *args, **kwargs: Response())
    assert "Verified disclosure evidence" in announcements.fetch_pdf_text("AN123")


def test_backfill_limits_work_to_selected_current_candidates(monkeypatch):
    import duckdb

    from stock_auditor.db import apply_migrations
    from stock_auditor.ingest import announcements

    class Client:
        def call(self, func, *, description):
            return func()

    seen = []

    def fetch(ann_id):
        seen.append(ann_id)
        return "text" * 40

    monkeypatch.setattr(announcements, "fetch_pdf_text", fetch)
    with duckdb.connect(":memory:") as db:
        apply_migrations(db)
        db.executemany(
            "INSERT INTO announcements (ann_id, code, ann_date) VALUES (?, ?, ?)",
            [
                ("AN1", "000001", date(2026, 10, 25)),
                ("AN2", "000002", date(2026, 10, 26)),
                ("AN3", "000001", date(2026, 11, 1)),
                ("AN4", "000001", date(2020, 1, 1)),
            ],
        )
        count, failures = announcements.backfill_announcement_text(
            db, Client(), codes=["000001"], as_of=date(2026, 10, 29), lookback_days=90
        )
        assert (count, failures, seen) == (1, {}, ["AN1"])
