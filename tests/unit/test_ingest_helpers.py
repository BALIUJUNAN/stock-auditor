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
