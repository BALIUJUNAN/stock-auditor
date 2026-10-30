"""申万行业归属采集：官方申万指数接口，一级/二级行业成分股。

申万官网证书链依赖 Windows 系统信任库，且会被本机代理拦截，因此这里用
``ssl.create_default_context()``（系统根证书）并关闭代理环境变量继承。
"""

from __future__ import annotations

import ssl
from datetime import datetime
from typing import Any

import duckdb
import httpx
import structlog

from stock_auditor.config import Settings
from stock_auditor.ingest.common import DataClient, clean_text, normalize_code

log = structlog.get_logger(__name__)

_UPDATE_SQL = """
UPDATE stock_universe
SET sw_l1 = ?, sw_l2 = ?, updated_at = ?
WHERE code = ?
"""

_SW_BASE = "https://www.swsresearch.com"
_INDEX_LIST_PATH = "/institute-sw/api/index_publish/current/"
_COMPONENTS_PATH = "/institute-sw/api/index_publish/details/component_stocks/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
_L1_LABEL = "一级行业"
_L2_LABEL = "二级行业"
_PAGE_SIZE = 50
_COMPONENT_PAGE_SIZE = 10000

_SSL_CONTEXT = ssl.create_default_context()


def _get(path: str, params: dict[str, str]) -> httpx.Response:
    response = httpx.get(
        f"{_SW_BASE}{path}",
        params=params,
        headers=_HEADERS,
        verify=_SSL_CONTEXT,
        trust_env=False,
        timeout=30,
    )
    response.raise_for_status()
    return response


def _fetch_index_list(level: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = _get(
            _INDEX_LIST_PATH,
            {"page": str(page), "page_size": str(_PAGE_SIZE), "indextype": level},
        ).json()
        data = payload.get("data") or {}
        batch = list(data.get("results") or [])
        results.extend(batch)
        total = int(data.get("count") or 0)
        if not batch or len(results) >= total:
            break
        page += 1
    return results


def _fetch_components(index_code: str) -> list[dict[str, Any]]:
    payload = _get(
        _COMPONENTS_PATH,
        {
            "swindexcode": index_code,
            "page": "1",
            "page_size": str(_COMPONENT_PAGE_SIZE),
        },
    ).json()
    data = payload.get("data") or {}
    return list(data.get("results") or [])


def _index_members(
    client: DataClient,
    level: str,
    indices: list[dict[str, Any]],
) -> dict[str, str]:
    """返回 ``{股票代码: 行业名称}``；单个指数失败时记录并跳过。"""
    members: dict[str, str] = {}
    for index in indices:
        index_code = clean_text(index.get("swindexcode"))
        index_name = clean_text(index.get("swindexname"))
        if not index_code or not index_name:
            continue
        try:
            records = client.call(
                lambda code=index_code: _fetch_components(code),
                description=f"申万{level}成分 {index_code}",
            )
        except Exception as exc:  # noqa: BLE001 - 单个行业失败不阻塞整批
            log.warning(
                "ingest.industry.constituents_failed",
                level=level,
                index=index_code,
                error=str(exc),
            )
            continue
        for record in records:
            raw_code = clean_text(record.get("stockcode"))
            if raw_code is None:
                continue
            try:
                code = normalize_code(raw_code)
            except ValueError:
                continue
            members[code] = index_name
    return members


def collect_industry(
    client: DataClient,
    settings: Settings,
) -> list[tuple[str, str, str]]:
    """返回 ``(code, sw_l1, sw_l2)``；遍历申万一级/二级行业指数成分。"""
    del settings  # 行业映射不依赖可调参数
    l1_indices = client.call(
        lambda: _fetch_index_list(_L1_LABEL),
        description="申万一级行业列表",
    )
    l2_indices = client.call(
        lambda: _fetch_index_list(_L2_LABEL),
        description="申万二级行业列表",
    )
    log.info(
        "ingest.industry.levels",
        l1=len(l1_indices),
        l2=len(l2_indices),
    )

    l1_names = _index_members(client, _L1_LABEL, l1_indices)
    l2_names = _index_members(client, _L2_LABEL, l2_indices)

    rows = [
        (code, l1_names[code], l2_names[code])
        for code in sorted(set(l1_names) & set(l2_names))
    ]
    log.info(
        "ingest.industry.collected",
        rows=len(rows),
        l1_members=len(l1_names),
        l2_members=len(l2_names),
    )
    return rows


def store_industry(
    connection: duckdb.DuckDBPyConnection,
    rows: list[tuple[str, str, str]],
) -> int:
    """更新股票池中的申万行业；返回实际被更新的股票数。"""
    if not rows:
        return 0
    before = connection.execute(
        "SELECT count(*) FROM stock_universe WHERE sw_l1 IS NOT NULL"
    ).fetchone()[0]
    now = datetime.now()
    connection.executemany(
        _UPDATE_SQL,
        [(l1, l2, now, code) for code, l1, l2 in rows],
    )
    after = connection.execute(
        "SELECT count(*) FROM stock_universe WHERE sw_l1 IS NOT NULL"
    ).fetchone()[0]
    return int(after) - int(before)
