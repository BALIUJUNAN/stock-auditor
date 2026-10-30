"""LLM 池落库：``llm_pool``。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import duckdb

from stock_auditor.funnel.pool import PoolEntry

_POOL_SQL = """
INSERT OR REPLACE INTO llm_pool (run_id, code, source, created_at)
VALUES (?, ?, ?, ?)
"""


def store_llm_pool(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
    entries: Sequence[PoolEntry],
) -> int:
    if not entries:
        return 0
    now = datetime.now()
    payload = [(run_id, entry.code, entry.source, now) for entry in entries]
    connection.executemany(_POOL_SQL, payload)
    return len(payload)
