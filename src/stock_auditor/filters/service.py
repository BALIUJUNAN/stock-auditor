"""过滤结果落库：``filter_log`` 与 ``veto_events``。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime

import duckdb

from stock_auditor.domain import FilterResult
from stock_auditor.filters.veto import VetoEvent

_FILTER_SQL = """
INSERT OR REPLACE INTO filter_log (run_id, code, passed, reasons, created_at)
VALUES (?, ?, ?, ?, ?)
"""

_VETO_SQL = """
INSERT OR REPLACE INTO veto_events
    (run_id, code, rule, level, detail, penalty, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""


def store_filter_results(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
    results: Sequence[FilterResult],
) -> int:
    if not results:
        return 0
    now = datetime.now()
    rows = [
        (
            run_id,
            result.code,
            result.passed,
            json.dumps(result.reasons, ensure_ascii=False),
            now,
        )
        for result in results
    ]
    connection.executemany(_FILTER_SQL, rows)
    return len(rows)


def store_veto_events(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
    events_by_code: Mapping[str, Sequence[VetoEvent]],
) -> int:
    now = datetime.now()
    rows = [
        (
            run_id,
            code,
            event.rule,
            event.level,
            event.detail,
            event.penalty,
            now,
        )
        for code, events in events_by_code.items()
        for event in events
    ]
    if not rows:
        return 0
    connection.executemany(_VETO_SQL, rows)
    return len(rows)
