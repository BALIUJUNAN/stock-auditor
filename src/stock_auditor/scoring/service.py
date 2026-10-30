"""评分结果落库：``quant_scores`` 与 ``final_scores``。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import duckdb

from stock_auditor.scoring.composite import CompositeResult

_QUANT_SQL = """
INSERT OR REPLACE INTO quant_scores
    (run_id, code, raw_values, industry_percentiles, scores, is_imputed,
     fundamental, momentum, tags, data_flag, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_FINAL_SQL = """
INSERT OR REPLACE INTO final_scores
    (run_id, code, raw_total, final_total, stars, is_yellow, is_veto, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


@dataclass(frozen=True)
class QuantScore:
    code: str
    fundamental: float
    momentum: float
    raw_values: dict[str, float | None] = field(default_factory=dict)
    industry_percentiles: dict[str, float | None] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)
    is_imputed: dict[str, bool] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    data_flag: str | None = None


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def store_quant_scores(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
    rows: Sequence[QuantScore],
) -> int:
    if not rows:
        return 0
    now = datetime.now()
    payload = [
        (
            run_id,
            row.code,
            _json(row.raw_values),
            _json(row.industry_percentiles),
            _json(row.scores),
            _json(row.is_imputed),
            row.fundamental,
            row.momentum,
            _json(row.tags),
            row.data_flag,
            now,
        )
        for row in rows
    ]
    connection.executemany(_QUANT_SQL, payload)
    return len(payload)


def store_final_scores(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
    rows: Mapping[str, CompositeResult],
) -> int:
    if not rows:
        return 0
    now = datetime.now()
    payload = [
        (
            run_id,
            code,
            result.raw_total,
            result.final_total,
            result.stars,
            result.is_yellow,
            result.is_veto,
            now,
        )
        for code, result in rows.items()
    ]
    connection.executemany(_FINAL_SQL, payload)
    return len(payload)
