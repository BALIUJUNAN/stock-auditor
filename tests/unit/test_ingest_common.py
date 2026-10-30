from __future__ import annotations

import os
from datetime import date

import duckdb
import pytest

from stock_auditor.ingest.common import (
    clean_number,
    direct_network,
    em_symbol,
    exchange_prefix,
    normalize_code,
    sina_symbol,
    to_date,
    upsert_rows,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("002773", "002773"),
        ("002773.SZ", "002773"),
        ("SZ002773", "002773"),
        (" sz002773 ", "002773"),
        ("600000.SH", "600000"),
    ],
)
def test_normalize_code(raw: str, expected: str) -> None:
    assert normalize_code(raw) == expected


@pytest.mark.parametrize("raw", ["12345", "ABCDEF", "SZ12345", ""])
def test_normalize_code_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_code(raw)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("600000", "sh"),
        ("688001", "sh"),
        ("000001", "sz"),
        ("300750", "sz"),
        ("920000", "bj"),
        ("430047", "bj"),
    ],
)
def test_exchange_prefix(code: str, expected: str) -> None:
    assert exchange_prefix(code) == expected


def test_symbols() -> None:
    assert sina_symbol("002773.SZ") == "sz002773"
    assert em_symbol("600000") == "SH600000"


def test_to_date_variants() -> None:
    assert to_date("2026-09-30") == date(2026, 9, 30)
    assert to_date("2026-09-30 00:00:00") == date(2026, 9, 30)
    assert to_date(date(2026, 9, 30)) == date(2026, 9, 30)
    assert to_date(None) is None
    assert to_date("NaT") is None
    assert to_date(float("nan")) is None


def test_clean_number_variants() -> None:
    assert clean_number("1.5") == 1.5
    assert clean_number(None) is None
    assert clean_number(float("nan")) is None
    assert clean_number("abc") is None


def test_upsert_rows_replaces_by_primary_key() -> None:
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE demo (code VARCHAR PRIMARY KEY, value DOUBLE)"
        )
        columns = ("code", "value")
        assert upsert_rows(connection, "demo", columns, [("000001", 1.0)]) == 1
        upsert_rows(connection, "demo", columns, [("000001", 2.0), ("000002", 3.0)])
        rows = connection.execute(
            "SELECT code, value FROM demo ORDER BY code"
        ).fetchall()
        assert rows == [("000001", 2.0), ("000002", 3.0)]
        assert upsert_rows(connection, "demo", columns, []) == 0


def test_direct_network_restores_environment() -> None:
    previous = os.environ.get("NO_PROXY")
    try:
        with direct_network():
            assert os.environ["NO_PROXY"] == "*"
            assert os.environ["no_proxy"] == "*"
        assert os.environ.get("NO_PROXY") == previous
    finally:
        if previous is None:
            os.environ.pop("NO_PROXY", None)
        else:
            os.environ["NO_PROXY"] = previous
