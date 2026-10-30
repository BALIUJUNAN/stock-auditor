"""采集层公共工具：代码规范化、日期清洗、限流与重试。"""

from __future__ import annotations

import math
import os
import re
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any

import duckdb
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from stock_auditor.config import Settings

log = structlog.get_logger(__name__)

_CODE_PATTERN = re.compile(r"^\d{6}$")


def normalize_code(raw: str) -> str:
    """把 ``002773.SZ`` / ``SZ002773`` / ``002773`` 统一成 ``002773``。"""
    text = str(raw).strip().upper()
    if "." in text:
        text = text.split(".", 1)[0]
    for prefix in ("SH", "SZ", "BJ"):
        if text.startswith(prefix) and len(text) == 8:
            text = text[2:]
            break
    if not _CODE_PATTERN.match(text):
        raise ValueError(f"非法股票代码：{raw!r}")
    return text


def exchange_prefix(code: str) -> str:
    """返回 ``sh`` / ``sz`` / ``bj``。"""
    code = normalize_code(code)
    if code.startswith("6"):
        return "sh"
    if code.startswith(("0", "3")):
        return "sz"
    if code.startswith(("4", "8", "9")):
        return "bj"
    raise ValueError(f"无法判断交易所：{code}")


def sina_symbol(code: str) -> str:
    return f"{exchange_prefix(code)}{normalize_code(code)}"


def em_symbol(code: str) -> str:
    return f"{exchange_prefix(code).upper()}{normalize_code(code)}"


def to_date(value: Any) -> date | None:
    """把 pandas Timestamp / 字符串 / date 转成 ``date``；空值返回 None。"""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "to_pydatetime"):
        converted = value.to_pydatetime()
        return converted.date() if isinstance(converted, datetime) else converted
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return None
    return datetime.fromisoformat(text[:10]).date()


def clean_number(value: Any) -> float | None:
    """转 float；NaN/Inf/空值返回 None。"""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return None
    return text


class DataClient:
    """统一处理请求间隔与指数退避重试。"""

    def __init__(self, settings: Settings) -> None:
        ingest = settings.ingest
        self._interval = ingest.request_interval_seconds
        self._max_retries = ingest.max_retries
        self._backoff = ingest.retry_backoff_seconds
        self._last_call = 0.0

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._interval:
            time.sleep(self._interval - elapsed)
        self._last_call = time.monotonic()

    def call(self, func: Any, *, description: str) -> Any:
        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(
                multiplier=max(self._backoff, 0.01),
                min=max(self._backoff, 0.01),
                max=max(self._backoff, 0.01) * 8,
            ),
            reraise=True,
        )
        def _run() -> Any:
            self._wait()
            return func()

        log.debug("ingest.call", description=description)
        return _run()


def frame_records(frame: Any) -> list[dict[str, Any]]:
    """把 AKShare 返回的 DataFrame 转成记录列表；None 或空表返回空列表。"""
    if frame is None:
        return []
    if getattr(frame, "empty", False):
        return []
    return list(frame.to_dict("records"))


def upsert_rows(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> int:
    """按主键覆盖写入；``table`` 与 ``columns`` 只能来自代码内常量。"""
    if not rows:
        return 0
    placeholders = ", ".join("?" for _ in columns)
    sql = f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    connection.executemany(sql, rows)
    return len(rows)


@contextmanager
def direct_network() -> Iterator[None]:
    """临时绕过系统代理，用于证书链依赖系统信任库的站点（申万）。

    进程内其他请求不受影响；退出时恢复原有环境变量。
    """
    keys = ("NO_PROXY", "no_proxy")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
