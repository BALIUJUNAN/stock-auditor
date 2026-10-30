"""每日核心池：持仓/重点关注名单 + 最近一期周报 ≥ 四星线（默认 75 分）。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import duckdb

from stock_auditor.config import Settings
from stock_auditor.funnel.watchlist import load_watchlist
from stock_auditor.pipeline.single import latest_run_id


def core_pool(
    connection: duckdb.DuckDBPyConnection,
    settings: Settings,
    *,
    as_of: date | None = None,
    codes: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """返回去重后的核心池；``codes`` 非空时直接作为核心池（手动指定）。"""
    if codes is not None:
        return tuple(dict.fromkeys(str(code) for code in codes))

    watchlist = load_watchlist(max_entries=settings.funnel.watchlist_max)
    ordered = list(watchlist.codes)

    weekly_run = latest_run_id(connection, "weekly", as_of=as_of)
    if weekly_run is None:
        return tuple(ordered)

    rows = connection.execute(
        "SELECT code FROM final_scores WHERE run_id = ? "
        "AND final_total >= ? AND COALESCE(is_veto, FALSE) = FALSE "
        "ORDER BY final_total DESC, code",
        [weekly_run, settings.score.star4],
    ).fetchall()
    for (code,) in rows:
        text = str(code)
        if text not in ordered:
            ordered.append(text)
    return tuple(ordered)
