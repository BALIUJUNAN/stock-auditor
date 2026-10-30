"""公告列表采集（东财公告大全）；正文解析在后续里程碑处理。"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import date, timedelta
from typing import Any

import duckdb
import pdfplumber
import requests
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
    url = excluded.url,
    text = COALESCE(excluded.text, announcements.text),
    text_hash = COALESCE(excluded.text_hash, announcements.text_hash)
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
            rows.extend(fetch_announcement_rows(client, code, begin_text, end_text))
        except Exception as exc:  # noqa: BLE001 - 单只失败不阻塞整批
            if hasattr(client, "record_failure"):
                client.record_failure("announcements", code, exc)
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


def fetch_pdf_text(ann_id: str) -> str:
    """Download an Eastmoney PDF by its validated announcement ID."""
    if not re.fullmatch(r"AN\d+", ann_id):
        raise ValueError("unsupported announcement ID")
    url = f"https://pdf.dfcfw.com/pdf/H2_{ann_id}_1.pdf"
    with requests.get(url, timeout=(10, 30), stream=True, allow_redirects=False) as response:
        response.raise_for_status()
        chunks = []
        size = 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 20 * 1024 * 1024:
                raise ValueError("announcement PDF exceeds 20 MiB")
            chunks.append(chunk)
    content = b"".join(chunks)
    if not content.startswith(b"%PDF-"):
        raise ValueError("announcement response is not a PDF")
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages[:80]).strip()
    if len(text) < 100:
        raise ValueError("announcement PDF contains insufficient extractable text")
    return text[:200000]


def backfill_announcement_text(
    connection: duckdb.DuckDBPyConnection,
    client: DataClient,
    *,
    limit: int = 100,
    codes: list[str] | None = None,
    as_of: date | None = None,
    lookback_days: int | None = None,
) -> tuple[int, dict[str, str]]:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS announcement_text_attempts "
        "(ann_id VARCHAR PRIMARY KEY, attempts INTEGER NOT NULL, last_error VARCHAR)"
    )
    if codes is not None and not codes:
        return 0, {}
    filters = ["(a.text IS NULL OR length(trim(a.text)) < 100)"]
    params: list[Any] = []
    if codes is not None:
        filters.append("a.code IN (" + ", ".join("?" for _ in codes) + ")")
        params.extend(codes)
    if as_of is not None:
        filters.append("a.ann_date <= ?")
        params.append(as_of)
        if lookback_days is not None:
            filters.append("a.ann_date >= ?")
            params.append(as_of - timedelta(days=lookback_days))
    rows = connection.execute(
        "SELECT a.ann_id FROM announcements a "
        "LEFT JOIN announcement_text_attempts t ON a.ann_id = t.ann_id "
        "WHERE " + " AND ".join(filters) + " "
        "ORDER BY COALESCE(t.attempts, 0), a.ann_date DESC, a.ann_id LIMIT ?",
        [*params, limit],
    ).fetchall()
    failures = {}
    success = 0
    for (ann_id,) in rows:
        try:
            body = client.call(
                lambda value=ann_id: fetch_pdf_text(value), description=f"公告正文 {ann_id}"
            )
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
            connection.execute(
                "UPDATE announcements SET text = ?, text_hash = ? WHERE ann_id = ?",
                [body, digest, ann_id],
            )
            success += 1
        except Exception as exc:
            failures[ann_id] = str(exc)
            connection.execute(
                "INSERT INTO announcement_text_attempts VALUES (?, 1, ?) "
                "ON CONFLICT (ann_id) DO UPDATE SET "
                "attempts = announcement_text_attempts.attempts + 1, "
                "last_error = excluded.last_error",
                [ann_id, str(exc)],
            )
            log.warning("ingest.announcement_text.failed", ann_id=ann_id, error=str(exc))
    return success, failures
