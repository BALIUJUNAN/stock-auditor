"""机构调研记录采集：东财数据中心按个股查询（原始 HTTP 接口）。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx
import structlog

from stock_auditor.config import Settings
from stock_auditor.ingest.common import DataClient, clean_text, normalize_code, to_date

log = structlog.get_logger(__name__)

RESEARCH_COLUMNS = ("code", "visit_date", "org")

_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_PAGE_SIZE = 50


def _fetch_page(code: str, page: int) -> list[dict[str, Any]]:
    params = {
        "sortColumns": "NOTICE_DATE",
        "sortTypes": "-1",
        "pageSize": str(_PAGE_SIZE),
        "pageNumber": str(page),
        "reportName": "RPT_ORG_SURVEY",
        "columns": "ALL",
        "quoteColumns": "",
        "quoteType": "0",
        "source": "WEB",
        "client": "WEB",
        "filter": f'(SECURITY_CODE="{code}")',
    }
    response = httpx.get(_URL, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    result = payload.get("result") or {}
    return list(result.get("data") or [])


def fetch_research_rows(
    client: DataClient,
    settings: Settings,
    code: str,
    cutoff: date,
) -> list[tuple[Any, ...]]:
    rows: dict[tuple[str, date, str], tuple[Any, ...]] = {}
    for page in range(1, settings.ingest.research_max_pages + 1):
        records = client.call(
            lambda current=page, symbol=code: _fetch_page(symbol, current),
            description=f"机构调研 {code} 第 {page} 页",
        )
        for record in records:
            visit_date = to_date(record.get("RECEIVE_START_DATE")) or to_date(
                record.get("NOTICE_DATE")
            )
            org = clean_text(record.get("RECEIVE_OBJECT")) or clean_text(
                record.get("INVESTIGATORS")
            )
            if visit_date is None or org is None or visit_date < cutoff:
                continue
            rows[(code, visit_date, org)] = (code, visit_date, org)
        if len(records) < _PAGE_SIZE:
            break
    return [rows[key] for key in sorted(rows)]


def collect_research(
    client: DataClient,
    settings: Settings,
    codes: list[str],
) -> list[tuple[Any, ...]]:
    """抓取 ``ingest.research_lookback_days`` 内的调研记录。"""
    cutoff = date.today() - timedelta(days=settings.ingest.research_lookback_days)
    rows: dict[tuple[str, date, str], tuple[Any, ...]] = {}
    for raw_code in codes:
        code = normalize_code(raw_code)
        try:
            for row in fetch_research_rows(client, settings, code, cutoff):
                rows[(row[0], row[1], row[2])] = row
        except Exception as exc:  # noqa: BLE001 - 单只失败不阻塞整批
            if hasattr(client, "record_failure"):
                client.record_failure("research", code, exc)
            log.error("ingest.research.failed", code=code, error=str(exc))
    result = [rows[key] for key in sorted(rows)]
    log.info("ingest.research.collected", rows=len(result))
    return result
