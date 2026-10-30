"""DuckDB 连接。数据库文件默认在 ``var/db/stock_auditor.duckdb``。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

from stock_auditor import paths

DB_FILENAME = "stock_auditor.duckdb"


def database_path() -> Path:
    """返回默认数据库文件路径。"""
    return paths.db_dir() / DB_FILENAME


@contextmanager
def connect(
    path: Path | None = None,
    read_only: bool = False,
) -> Iterator[duckdb.DuckDBPyConnection]:
    """打开数据库连接，退出上下文时关闭。父目录不存在会自动创建。"""
    db_path = Path(path) if path is not None else database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(db_path), read_only=read_only)
    try:
        yield connection
    finally:
        connection.close()
