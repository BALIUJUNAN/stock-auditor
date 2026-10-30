"""公告列表采集（东财公告大全）；正文解析在后续里程碑处理。"""

from __future__ import annotations

import hashlib
import re
from datetime import date, timedelta
from typing import Any

import duckdb
import structlog

from stock_auditor.config import Settings
from stock_auditor.ingest.common import (
    DataClient,
    clean_text,
    frame_records,
    normalize_code,
    to_date,
)

log = structlog.get_logger(__name__)

_ANN_ID_PATTERN = re.compile(r"(AN\d+)")

_UPSERT_SQL = """
INSERT INTO announcements (ann_id, code, ann_date, title, category, url, text, text_hash)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (ann_id) DO UPDATE SET
    code = excluded.code,
    ann_date = excluded.ann_date,
    title = excluded.title,
    category = excluded.category,
    url = excluded.url
"""


def _ak() -> Any:
    import akshare as ak

    return ak


def announcement_id(url: str | None, code: str, ann_date: date | None, title: str) -> str:
    """优先使用东财公告编号（AN...）；缺失时用内容摘要生成稳定 ID。"""
    if url:
        match = _ANN_ID_PATTERN.search(url)
        if match:
            return match.group(1)
    digest = hashlib.sha1(f"{code}|{ann_date}|{title}".encode()).hexdigest()[:16]
    return f"{code}-{digest}"


def fetch_announcement_rows(
    client: DataClient,
    code: str,
    begin_text: str,
    end_text: str,
) -> list[tuple[Any, ...]]:
    frame = client.call(
        lambda security=code: _ak().stock_individual_notice_report(
            security=security,
            symbol="全部",
            begin_date=begin_text,
            end_date=end_text,
        ),
        description=f"公告列表 {code}",
    )
    rows: list[tuple[Any, ...]] = []
    for record in frame_records(frame):
        ann_date = to_date(record.get("公告日期"))
        title = clean_text(record.get("公告标题"))
        if title is None:
            continue
        url = clean_text(record.get("网址"))
        rows.append(
            (
                announcement_id(url, code, ann_date, title),
                code,
                ann_date,
                title,
                clean_text(record.get("公告类型")),
                url,
                None,
                None,
            )
        )
    return rows


def collect_announcements(
    client: DataClient,
    settings: Settings,
    codes: list[str],
) -> list[tuple[Any, ...]]:
    """按 ``ingest.announcement_lookback_days`` 抓取个股公告。"""
    end = date.today()
    begin = end - timedelta(days=settings.ingest.announcement_lookback_days)
    begin_text = begin.strftime("%Y%m%d")
    end_text = end.strftime("%Y%m%d")
    rows: list[tuple[Any, ...]] = []
    for raw_code in codes:
        code = normalize_code(raw_code)
        try:
            rows.extend(
                fetch_announcement_rows(client, code, begin_text, end_text)
            )
        except Exception as exc:  # noqa: BLE001 - 单只失败不阻塞整批
            log.error("ingest.announcements.failed", code=code, error=str(exc))
    log.info("ingest.announcements.collected", rows=len(rows))
    return rows


def store_announcements(
    connection: duckdb.DuckDBPyConnection,
    rows: list[tuple[Any, ...]],
) -> int:
    """写入公告；重复公告只更新元数据，保留已解析的正文。"""
    if not rows:
        return 0
    connection.executemany(_UPSERT_SQL, rows)
    return len(rows)
