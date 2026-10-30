"""股票池采集：交易所上市列表、板块归属与 ST 标记。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import duckdb
import structlog

from stock_auditor.config import Settings
from stock_auditor.ingest.common import DataClient, clean_text, normalize_code, to_date

log = structlog.get_logger(__name__)

_COLUMNS = ("code", "name", "board", "list_date", "is_st")

_UPSERT_SQL = """
INSERT INTO stock_universe (code, name, board, list_date, is_st, updated_at)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (code) DO UPDATE SET
    name = excluded.name,
    board = excluded.board,
    list_date = excluded.list_date,
    is_st = excluded.is_st,
    updated_at = excluded.updated_at
"""


def _ak() -> Any:
    import akshare as ak

    return ak


def board_from_code(code: str) -> str:
    """按代码段判断板块，作为交易所列表缺失时的兜底。"""
    code = normalize_code(code)
    if code.startswith(("688", "689")):
        return "star"
    if code.startswith(("300", "301")):
        return "chinext"
    if code.startswith("6"):
        return "sh_main"
    if code.startswith(("0", "1", "2", "3")):
        return "sz_main"
    if code.startswith(("4", "8", "9")):
        return "bse"
    raise ValueError(f"无法判断板块：{code}")


def is_st_name(name: str, keywords: list[str]) -> bool:
    """名称中包含任一排除关键词（ST/*ST/退）即视为风险警示。"""
    return any(keyword in name for keyword in keywords)


def _record_code(record: dict[str, Any]) -> str | None:
    raw = clean_text(record.get("证券代码")) or clean_text(record.get("A股代码"))
    if raw is None:
        raw = clean_text(record.get("code"))
    if raw is None:
        return None
    try:
        return normalize_code(raw)
    except ValueError:
        return None


def _collect_exchange_rows(
    client: DataClient,
    settings: Settings,
    merged: dict[str, tuple[Any, ...]],
) -> None:
    def _add(code: str, name: str, board: str, list_date: Any) -> None:
        merged[code] = (
            code,
            name,
            board,
            to_date(list_date),
            is_st_name(name, settings.universe.exclude_name_keywords),
        )

    sh_main = client.call(
        lambda: _ak().stock_info_sh_name_code(symbol="主板A股"),
        description="上交所主板列表",
    )
    for record in sh_main.to_dict("records"):
        code = _record_code(record)
        name = clean_text(record.get("证券简称"))
        if code and name:
            _add(code, name, "sh_main", record.get("上市日期"))

    star = client.call(
        lambda: _ak().stock_info_sh_name_code(symbol="科创板"),
        description="上交所科创板列表",
    )
    for record in star.to_dict("records"):
        code = _record_code(record)
        name = clean_text(record.get("证券简称"))
        if code and name:
            _add(code, name, "star", record.get("上市日期"))

    sz = client.call(
        lambda: _ak().stock_info_sz_name_code(symbol="A股列表"),
        description="深交所股票列表",
    )
    for record in sz.to_dict("records"):
        code = _record_code(record)
        name = clean_text(record.get("A股简称"))
        if code and name:
            board = "chinext" if clean_text(record.get("板块")) == "创业板" else "sz_main"
            _add(code, name, board, record.get("A股上市日期"))

    bj = client.call(
        lambda: _ak().stock_info_bj_name_code(),
        description="北交所股票列表",
    )
    for record in bj.to_dict("records"):
        code = _record_code(record)
        name = clean_text(record.get("证券简称"))
        if code and name:
            _add(code, name, "bse", record.get("上市日期"))

    # 补漏：交易所列表偶有缺项时，用全市场代码简称表兜底。
    every = client.call(
        lambda: _ak().stock_info_a_code_name(),
        description="全市场股票代码表",
    )
    for record in every.to_dict("records"):
        raw_code = clean_text(record.get("code"))
        name = clean_text(record.get("name"))
        if not raw_code or not name:
            continue
        try:
            code = normalize_code(raw_code)
        except ValueError:
            continue
        if code not in merged:
            try:
                board = board_from_code(code)
            except ValueError:
                continue
            _add(code, name, board, None)


def collect_universe(client: DataClient, settings: Settings) -> list[tuple[Any, ...]]:
    """抓取沪深京 A 股列表，返回待写入 ``stock_universe`` 的行。"""
    merged: dict[str, tuple[Any, ...]] = {}
    _collect_exchange_rows(client, settings, merged)
    rows = [merged[code] for code in sorted(merged)]
    log.info("ingest.universe.collected", rows=len(rows))
    return rows


def store_universe(
    connection: duckdb.DuckDBPyConnection,
    rows: list[tuple[Any, ...]],
) -> int:
    """写入股票池；已有记录的申万行业字段保持不变。"""
    if not rows:
        return 0
    now = datetime.now()
    connection.executemany(_UPSERT_SQL, [(*row, now) for row in rows])
    return len(rows)
