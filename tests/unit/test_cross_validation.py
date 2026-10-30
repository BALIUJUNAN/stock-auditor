from __future__ import annotations

from datetime import date

import pytest

from stock_auditor.commercial.base import FinancialRecord
from stock_auditor.commercial.cross_validation import cross_validate, relative_deviation

MAX_DEVIATION = 0.05
MISSING = "未交叉验证"
SUSPECT = "数据存疑"
PERIOD = date(2025, 12, 31)


def _record(
    code: str,
    *,
    revenue: float | None = 100.0,
    net_profit_parent: float | None = 10.0,
    ocf: float | None = 20.0,
    period: date = PERIOD,
) -> FinancialRecord:
    return FinancialRecord(
        code=code,
        report_period=period,
        revenue=revenue,
        net_profit_parent=net_profit_parent,
        ocf=ocf,
    )


def _validate(
    codes: list[str],
    open_records: list[FinancialRecord],
    commercial_records: list[FinancialRecord],
) -> dict[str, str | None]:
    return cross_validate(
        codes,
        open_records,
        commercial_records,
        max_deviation=MAX_DEVIATION,
        missing_label=MISSING,
        suspect_label=SUSPECT,
    )


@pytest.mark.parametrize(
    ("open_value", "commercial_value", "expected"),
    [
        (100.0, 100.0, 0.0),
        (100.0, 104.0, 4.0 / 104.0),
        (0.0, 0.0, 0.0),
        (0.0, 100.0, 1.0),
    ],
)
def test_relative_deviation(
    open_value: float, commercial_value: float, expected: float
) -> None:
    assert relative_deviation(open_value, commercial_value) == pytest.approx(expected)


def test_matching_records_pass() -> None:
    flags = _validate(["002773"], [_record("002773")], [_record("002773")])
    assert flags == {"002773": None}


def test_small_deviation_passes() -> None:
    flags = _validate(
        ["002773"],
        [_record("002773", revenue=100.0)],
        [_record("002773", revenue=104.0)],
    )
    assert flags["002773"] is None


def test_any_field_over_threshold_marks_suspect() -> None:
    flags = _validate(
        ["002773"],
        [_record("002773", revenue=100.0, net_profit_parent=10.0, ocf=20.0)],
        [_record("002773", revenue=100.0, net_profit_parent=11.0, ocf=20.0)],
    )
    assert flags["002773"] == SUSPECT


def test_missing_commercial_records_marks_missing() -> None:
    flags = _validate(["002773"], [_record("002773")], [])
    assert flags["002773"] == MISSING


def test_missing_commercial_period_marks_missing() -> None:
    other_period = date(2025, 9, 30)
    flags = _validate(
        ["002773"],
        [_record("002773", period=PERIOD)],
        [_record("002773", period=other_period)],
    )
    assert flags["002773"] == MISSING


def test_no_comparable_fields_marks_missing() -> None:
    flags = _validate(
        ["002773"],
        [_record("002773", revenue=None, net_profit_parent=None, ocf=None)],
        [_record("002773")],
    )
    assert flags["002773"] == MISSING


def test_missing_single_field_does_not_block_other_comparisons() -> None:
    flags = _validate(
        ["002773"],
        [_record("002773", revenue=None, net_profit_parent=10.0, ocf=20.0)],
        [_record("002773", revenue=999.0, net_profit_parent=10.0, ocf=20.0)],
    )
    assert flags["002773"] is None


def test_each_code_is_reported() -> None:
    flags = _validate(
        ["002773", "002185"],
        [_record("002773")],
        [_record("002773")],
    )
    assert flags == {"002773": None, "002185": MISSING}
