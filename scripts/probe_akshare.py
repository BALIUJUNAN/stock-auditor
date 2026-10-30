"""探测 AKShare 数据接口在本机的可用性。

每个探针在独立子进程中执行，避免单个接口卡死或崩溃影响整体。
结果写入 ``var/probe/akshare_results.json``，用于维护 ``docs/data_sources.md``。

用法::

    uv run python scripts/probe_akshare.py --list
    uv run python scripts/probe_akshare.py --all
    uv run python scripts/probe_akshare.py --only stock_zh_a_daily,sw_index_first_info
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "var" / "probe" / "akshare_results.json"
RESULT_MARKER = "@@AKSHARE_PROBE@@"
TODAY = datetime.now().strftime("%Y%m%d")
ONE_YEAR_AGO = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
YESTERDAY = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
_DAYS_SINCE_FRIDAY = (datetime.now().weekday() - 4) % 7 or 7
LAST_FRIDAY = (datetime.now() - timedelta(days=_DAYS_SINCE_FRIDAY)).strftime("%Y%m%d")

ProbeFunc = Callable[[], Any]


@dataclass(frozen=True)
class Probe:
    name: str
    description: str
    func: ProbeFunc
    direct: bool = False
    timeout: int = 90
    params: dict[str, Any] = field(default_factory=dict)
    covers: tuple[str, ...] = ()
    update: str = ""
    rate_limit: str = ""
    required: bool = True


@dataclass(frozen=True)
class DataRequirement:
    key: str
    title: str
    primary: str
    backup: str


DATA_REQUIREMENTS: list[DataRequirement] = [
    DataRequirement("universe", "股票列表、简称、上市日期、板块", "AKShare", "商业源"),
    DataRequirement("industry", "申万 2021 一级 / 二级行业归属", "AKShare", "商业源"),
    DataRequirement(
        "daily", "日线行情（前复权）、成交量、成交额、换手率", "AKShare", "商业源"
    ),
    DataRequirement("financials", "财务三表与指标（含公告日）", "AKShare", "商业源（交叉验证）"),
    DataRequirement("valuation", "PE / PB / PS 历史序列", "AKShare", "商业源"),
    DataRequirement("consensus", "一致预期（未来 1~2 年净利润、营收）", "商业源", "—"),
    DataRequirement(
        "announcements", "公告列表与正文", "AKShare（巨潮资讯 / 东财）", "商业源（正文）"
    ),
    DataRequirement("pledge", "股权质押比例", "AKShare", "商业源"),
    DataRequirement("research", "机构调研记录", "AKShare", "商业源"),
    DataRequirement("earnings", "财报预约披露日期", "AKShare", "商业源"),
    DataRequirement("index", "沪深 300 与申万行业指数日线", "AKShare", "—"),
]

NOTES = """\
## 结论与注意事项

- 当前环境为 Windows，系统代理会拦截部分行情站点。东财 `push2his` 系列
  （`stock_zh_a_hist`、`index_zh_a_hist`、`stock_zh_index_daily_em`）在本机不可达；
  日线主源改用新浪 `stock_zh_a_daily` 或腾讯 `stock_zh_a_hist_tx`，指数使用新浪
  `stock_zh_index_daily` 或申万 `index_hist_sw`。
- 申万行业相关接口需要系统证书信任；探测时对相关接口设置 `NO_PROXY=*` 并注入
  `truststore`（仅探测脚本使用，正式采集需在部署环境确认证书与代理策略）。
- `stock_industry_clf_hist_sw` 返回申万历史分类的 `industry_code`（如 `440101`），
  需结合 `sw_index_first_info` / `sw_index_second_info` / `sw_index_third_cons`
  建立代码到一级/二级名称的映射；映射规则在 T0.4 实现并用 7 只校准股核对。
- 公告列表可用东财 `stock_notice_report` / `stock_individual_notice_report`（返回标题、
  分类、日期、详情页 URL）。巨潮 `stock_zh_a_disclosure_report_cninfo` 在本环境多次
  被限流（返回非 JSON），它是正文 PDF 的主要入口，正式采集必须做指数退避重试并缓存。
  正文 PDF 下载后再用 pdfplumber 解析；扫描件按配置 `ingest.skip_scanned_pdf` 跳过。
- 一致预期以商业源为主。东财/同花顺开源接口仅作探测与临时校验，字段含义和稳定性
  不满足 PIT 要求，不写入正式一致预期表。
- 估值首选东财 `stock_value_em`：一次返回全部历史，含 PE(TTM)/PE(静)/市净率/市销率/总市值；
  百度接口仅作 PE/PB 备用（该接口不提供市销率）。
- 东财财务指标接口 `stock_financial_analysis_indicator_em` 的 `symbol` 必须带市场后缀
  （如 `002773.SZ`），否则接口返回空结果。返回字段含 `NOTICE_DATE`、`ROEJQ`、`ROIC`、
  `ZCFZL`、`INTEREST_DEBT_RATIO`，可直接用于 PIT 与财务健康度计算。
- 机构调研按个股过滤的原始接口（`em_research_visits_by_stock`）可用；AKShare 的
  `stock_jgdy_detail_em` 会从起始日全量分页，单日数百页，正式采集不要使用。
- 所有采集函数必须支持断点续传、指数退避重试；请求间隔等参数在 T0.4 写入
  `config/settings.yaml` 的 `ingest` 分组，不在代码中硬编码。
"""


def _coverage_status(results: list[dict[str, Any]], key: str) -> str:
    required = [
        probe.name for probe in PROBES if key in probe.covers and probe.required
    ]
    if not required:
        return "待实现"
    matched = [item for item in results if item["name"] in required]
    if not matched:
        return "未探测"
    ok_count = sum(1 for item in matched if item["ok"])
    if ok_count == len(required):
        return "可用"
    if ok_count == 0:
        return "不可用"
    return "部分可用"


def _render_markdown(results: list[dict[str, Any]], generated_at: str) -> str:
    lines: list[str] = [
        "# 数据源探测结果",
        "",
        f"> 由 `uv run python scripts/probe_akshare.py` 自动生成，生成时间：{generated_at}。",
        "> 重新运行脚本会覆盖本文件；人工结论请写在 `NOTES` 常量中。",
        "",
        "## 5.1 数据需求覆盖情况",
        "",
        "| 数据 | 主来源 | 备用 / 校验 | 覆盖探针 | 状态 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for requirement in DATA_REQUIREMENTS:
        names = [
            f"`{probe.name}`" + ("" if probe.required else "（可选）")
            for probe in PROBES
            if requirement.key in probe.covers
        ]
        probes_text = ", ".join(names) or "—"
        status = _coverage_status(results, requirement.key)
        lines.append(
            f"| {requirement.title} | {requirement.primary} | {requirement.backup} "
            f"| {probes_text} | {status} |"
        )
    lines.extend(["", "## 接口明细", ""])
    for item in results:
        probe = PROBE_MAP[item["name"]]
        status = "可用" if item["ok"] else f"不可用（{item['error_type']}）"
        lines.append(f"### `{probe.name}`")
        lines.append("")
        lines.append(f"- 说明：{probe.description}")
        if probe.params:
            params = ", ".join(
                f"`{key}={value}`" for key, value in probe.params.items()
            )
            lines.append(f"- 参数：{params}")
        else:
            lines.append("- 参数：无")
        if probe.covers:
            titles = [
                requirement.title
                for requirement in DATA_REQUIREMENTS
                if requirement.key in probe.covers
            ]
            lines.append(f"- 覆盖数据：{'；'.join(titles)}")
        lines.append(f"- 更新频率：{probe.update or '未确认'}")
        lines.append(f"- 限流情况：{probe.rate_limit or '未确认'}")
        if probe.direct:
            lines.append("- 网络：直连（`NO_PROXY=*`，必要时注入系统信任库）")
        lines.append(f"- 状态：{status}")
        if item["ok"]:
            lines.append(f"- 行数：{item['rows']}；耗时：{item['elapsed_s']}s")
            lines.append("- 返回字段：")
            lines.append("")
            lines.append("```text")
            columns = item["columns"]
            for start in range(0, len(columns), 8):
                lines.append(", ".join(columns[start : start + 8]))
            lines.append("```")
            lines.append("")
            sample = json.dumps(item["sample"], ensure_ascii=False)
            if len(sample) > 1500:
                sample = sample[:1500] + "…（已截断）"
            lines.append("- 样例（前 2 行）：")
            lines.append("")
            lines.append("```json")
            lines.append(sample)
            lines.append("```")
        else:
            lines.append(f"- 错误：`{item['error']}`")
            lines.append(f"- 耗时：{item['elapsed_s']}s")
        lines.append("")
    lines.append(NOTES)
    return "\n".join(lines).rstrip() + "\n"


def _write_doc(
    results: list[dict[str, Any]], doc_path: Path, generated_at: str
) -> None:
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(
        _render_markdown(results, generated_at), encoding="utf-8"
    )
    print(f"文档已写入 {doc_path}")


def _ak() -> Any:
    import akshare as ak

    return ak


def _maybe_inject_truststore() -> bool:
    """部分站点（申万）证书链依赖系统信任库；仅在探测脚本中尝试。"""
    try:
        import truststore
    except ImportError:
        return False
    truststore.inject_into_ssl()
    return True


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return str(value)


def _fetch_research_visits_by_stock() -> Any:
    """按个股过滤东财调研接口，避免全市场分页。"""
    import httpx
    import pandas as pd

    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "sortColumns": "NOTICE_DATE",
        "sortTypes": "-1",
        "pageSize": "50",
        "pageNumber": "1",
        "reportName": "RPT_ORG_SURVEY",
        "columns": "ALL",
        "quoteColumns": "",
        "quoteType": "0",
        "source": "WEB",
        "client": "WEB",
        "filter": '(SECURITY_CODE="002773")',
    }
    response = httpx.get(url, params=params, timeout=30)
    response.raise_for_status()
    return pd.DataFrame(response.json()["result"]["data"])


def _run_probe(probe: Probe) -> dict[str, Any]:
    started = datetime.now()
    result: dict[str, Any] = {
        "name": probe.name,
        "description": probe.description,
        "params": probe.params,
        "direct": probe.direct,
        "ok": False,
        "rows": None,
        "columns": [],
        "sample": [],
        "elapsed_s": None,
        "error_type": None,
        "error": None,
        "truststore": False,
    }
    try:
        if probe.direct:
            result["truststore"] = _maybe_inject_truststore()
        for attempt in range(1, 3):
            result["attempts"] = attempt
            try:
                frame = probe.func()
            except Exception:  # noqa: BLE001 - 网络抖动时重试一次
                if attempt == 1:
                    time.sleep(2)
                    continue
                raise
            result["ok"] = True
            result["rows"] = int(len(frame))
            result["columns"] = [str(column) for column in frame.columns]
            sample = frame.head(2).to_dict(orient="records")
            result["sample"] = [
                {str(key): _json_safe(value) for key, value in row.items()}
                for row in sample
            ]
            break
    except Exception as exc:  # noqa: BLE001 - 探测需要记录任意异常
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)[:500]
    finally:
        result["elapsed_s"] = round((datetime.now() - started).total_seconds(), 2)
    return result


PROBES: list[Probe] = [
    Probe(
        "stock_info_a_code_name",
        "A 股代码与名称列表",
        lambda: _ak().stock_info_a_code_name(),
        params={},
    ),
    Probe(
        "stock_info_sh_name_code",
        "上交所股票列表（含上市日期、板块）",
        lambda: _ak().stock_info_sh_name_code(symbol="主板A股"),
        params={"symbol": "主板A股"},
    ),
    Probe(
        "stock_info_sh_name_code_kcb",
        "上交所科创板股票列表（含上市日期）",
        lambda: _ak().stock_info_sh_name_code(symbol="科创板"),
        params={"symbol": "科创板"},
    ),
    Probe(
        "stock_info_sz_name_code",
        "深交所股票列表（含上市日期、板块）",
        lambda: _ak().stock_info_sz_name_code(symbol="A股列表"),
        params={"symbol": "A股列表"},
    ),
    Probe(
        "stock_info_bj_name_code",
        "北交所股票列表（含上市日期）",
        lambda: _ak().stock_info_bj_name_code(),
        params={},
    ),
    Probe(
        "stock_individual_info_em",
        "东财个股概况（上市时间、行业、总市值）",
        lambda: _ak().stock_individual_info_em(symbol="002773", timeout=30),
        params={"symbol": "002773"},
    ),
    Probe(
        "stock_zh_a_daily",
        "新浪 A 股日线（002773，前复权）",
        lambda: _ak().stock_zh_a_daily(
            symbol="sz002773",
            start_date=ONE_YEAR_AGO,
            end_date=TODAY,
            adjust="qfq",
        ),
        params={"symbol": "sz002773", "adjust": "qfq"},
    ),
    Probe(
        "stock_zh_a_hist",
        "东财 A 股日线（002773，前复权；已知可能不可用）",
        lambda: _ak().stock_zh_a_hist(
            symbol="002773",
            period="daily",
            start_date=ONE_YEAR_AGO,
            end_date=TODAY,
            adjust="qfq",
        ),
        params={"symbol": "002773", "adjust": "qfq"},
    ),
    Probe(
        "stock_zh_a_hist_tx",
        "腾讯 A 股日线（002773，前复权）",
        lambda: _ak().stock_zh_a_hist_tx(
            symbol="sz002773",
            start_date=ONE_YEAR_AGO,
            end_date=TODAY,
            adjust="qfq",
            timeout=30,
        ),
        params={"symbol": "sz002773", "adjust": "qfq"},
    ),
    Probe(
        "stock_zh_valuation_baidu_pe",
        "百度估值：市盈率(TTM)，近一年",
        lambda: _ak().stock_zh_valuation_baidu(
            symbol="002773", indicator="市盈率(TTM)", period="近一年"
        ),
        params={"symbol": "002773", "indicator": "市盈率(TTM)", "period": "近一年"},
    ),
    Probe(
        "stock_zh_valuation_baidu_pb",
        "百度估值：市净率，近一年",
        lambda: _ak().stock_zh_valuation_baidu(
            symbol="002773", indicator="市净率", period="近一年"
        ),
        params={"symbol": "002773", "indicator": "市净率", "period": "近一年"},
    ),
    Probe(
        "stock_value_em",
        "东财估值分析（002773，含 PE/PB/PS/总市值，日频）",
        lambda: _ak().stock_value_em(symbol="002773"),
        params={"symbol": "002773"},
    ),
    Probe(
        "stock_zh_valuation_baidu_pe_5y",
        "百度估值：市盈率(TTM)，近五年",
        lambda: _ak().stock_zh_valuation_baidu(
            symbol="002773", indicator="市盈率(TTM)", period="近五年"
        ),
        params={"symbol": "002773", "indicator": "市盈率(TTM)", "period": "近五年"},
    ),
    Probe(
        "stock_financial_abstract_ths",
        "同花顺财务摘要（002773，按报告期）",
        lambda: _ak().stock_financial_abstract_ths(symbol="002773", indicator="按报告期"),
        params={"symbol": "002773", "indicator": "按报告期"},
    ),
    Probe(
        "stock_financial_analysis_indicator_em",
        "东财财务分析指标（002773，按报告期）",
        lambda: _ak().stock_financial_analysis_indicator_em(
            symbol="002773.SZ", indicator="按报告期"
        ),
        params={"symbol": "002773.SZ", "indicator": "按报告期"},
    ),
    Probe(
        "sw_index_first_info",
        "申万一级行业列表",
        lambda: _ak().sw_index_first_info(),
        direct=True,
        params={},
    ),
    Probe(
        "sw_index_second_info",
        "申万二级行业列表",
        lambda: _ak().sw_index_second_info(),
        direct=True,
        params={},
    ),
    Probe(
        "sw_index_third_cons",
        "申万三级行业成分（801120.SI）",
        lambda: _ak().sw_index_third_cons(symbol="801120.SI"),
        direct=True,
        params={"symbol": "801120.SI"},
    ),
    Probe(
        "stock_industry_clf_hist_sw",
        "申万历史分类（全量）",
        lambda: _ak().stock_industry_clf_hist_sw(),
        direct=True,
        timeout=120,
        params={},
    ),
    Probe(
        "index_hist_sw",
        "申万指数日线（801120）",
        lambda: _ak().index_hist_sw(symbol="801120", period="day"),
        direct=True,
        params={"symbol": "801120", "period": "day"},
    ),
    Probe(
        "stock_zh_a_disclosure_report_cninfo",
        "巨潮公告（002773，近一年）",
        lambda: _ak().stock_zh_a_disclosure_report_cninfo(
            symbol="002773",
            market="沪深京",
            start_date=ONE_YEAR_AGO,
            end_date=TODAY,
        ),
        params={"symbol": "002773", "market": "沪深京"},
    ),
    Probe(
        "stock_notice_report",
        "东财公告（全部，昨日）",
        lambda: _ak().stock_notice_report(symbol="全部", date=YESTERDAY),
        params={"symbol": "全部", "date": YESTERDAY},
    ),
    Probe(
        "stock_individual_notice_report",
        "东财个股公告（002773，近一年）",
        lambda: _ak().stock_individual_notice_report(
            security="002773",
            symbol="全部",
            begin_date=ONE_YEAR_AGO,
            end_date=TODAY,
        ),
        params={"security": "002773", "symbol": "全部"},
    ),
    Probe(
        "stock_gpzy_individual_pledge_ratio_detail_em",
        "东财个股质押明细（600664，有质押记录）",
        lambda: _ak().stock_gpzy_individual_pledge_ratio_detail_em(symbol="600664"),
        params={"symbol": "600664"},
    ),
    Probe(
        "stock_gpzy_pledge_ratio_em",
        "东财全市场质押比例（最近一个周五）",
        lambda: _ak().stock_gpzy_pledge_ratio_em(date=LAST_FRIDAY),
        params={"date": LAST_FRIDAY},
    ),
    Probe(
        "stock_jgdy_tj_em",
        "东财机构调研统计（近一年）",
        lambda: _ak().stock_jgdy_tj_em(date=ONE_YEAR_AGO),
        params={"date": ONE_YEAR_AGO},
    ),
    Probe(
        "stock_jgdy_detail_em",
        "东财机构调研明细（昨日；接口按起始日全量分页，数据量大）",
        lambda: _ak().stock_jgdy_detail_em(date=YESTERDAY),
        timeout=180,
        params={"date": YESTERDAY},
    ),
    Probe(
        "em_research_visits_by_stock",
        "东财调研记录（按个股过滤，002773，前 50 条）",
        _fetch_research_visits_by_stock,
        params={"security_code": "002773", "page_size": 50},
    ),
    Probe(
        "stock_report_disclosure",
        "财报预约披露时间（2026三季）",
        lambda: _ak().stock_report_disclosure(market="沪深京", period="2026三季"),
        params={"market": "沪深京", "period": "2026三季"},
    ),
    Probe(
        "index_zh_a_hist",
        "东财指数日线（000300）",
        lambda: _ak().index_zh_a_hist(
            symbol="000300", period="daily", start_date=ONE_YEAR_AGO, end_date=TODAY
        ),
        params={"symbol": "000300"},
    ),
    Probe(
        "stock_zh_index_daily",
        "新浪指数日线（sh000300）",
        lambda: _ak().stock_zh_index_daily(symbol="sh000300"),
        params={"symbol": "sh000300"},
    ),
    Probe(
        "stock_zh_index_daily_em",
        "东财指数日线（sh000300）",
        lambda: _ak().stock_zh_index_daily_em(
            symbol="sh000300", start_date=ONE_YEAR_AGO, end_date=TODAY
        ),
        params={"symbol": "sh000300"},
    ),
    Probe(
        "tool_trade_date_hist_sina",
        "新浪交易日历",
        lambda: _ak().tool_trade_date_hist_sina(),
        params={},
    ),
    Probe(
        "stock_profit_forecast_em",
        "东财一致预期（002773；已知可能报错）",
        lambda: _ak().stock_profit_forecast_em(symbol="002773"),
        params={"symbol": "002773"},
    ),
    Probe(
        "stock_profit_forecast_em_all",
        "东财一致预期（无参，全市场）",
        lambda: _ak().stock_profit_forecast_em(),
        timeout=120,
        params={},
    ),
    Probe(
        "stock_profit_forecast_ths",
        "同花顺一致预期（002773，预测年报每股收益）",
        lambda: _ak().stock_profit_forecast_ths(
            symbol="002773", indicator="预测年报每股收益"
        ),
        params={"symbol": "002773", "indicator": "预测年报每股收益"},
    ),
    Probe(
        "stock_balance_sheet_by_report_em",
        "东财资产负债表（SZ002773，按报告期）",
        lambda: _ak().stock_balance_sheet_by_report_em(symbol="SZ002773"),
        params={"symbol": "SZ002773"},
    ),
    Probe(
        "stock_profit_sheet_by_report_em",
        "东财利润表（SZ002773，按报告期）",
        lambda: _ak().stock_profit_sheet_by_report_em(symbol="SZ002773"),
        params={"symbol": "SZ002773"},
    ),
    Probe(
        "stock_cash_flow_sheet_by_report_em",
        "东财现金流量表（SZ002773，按报告期）",
        lambda: _ak().stock_cash_flow_sheet_by_report_em(symbol="SZ002773"),
        params={"symbol": "SZ002773"},
    ),
    Probe(
        "stock_financial_report_sina_cashflow",
        "新浪现金流量表（sz002773）",
        lambda: _ak().stock_financial_report_sina(stock="sz002773", symbol="现金流量表"),
        params={"stock": "sz002773", "symbol": "现金流量表"},
    ),
    Probe(
        "stock_financial_report_sina_balance",
        "新浪资产负债表（sz002773）",
        lambda: _ak().stock_financial_report_sina(stock="sz002773", symbol="资产负债表"),
        params={"stock": "sz002773", "symbol": "资产负债表"},
    ),
]

_METADATA: dict[str, dict[str, Any]] = {
    "stock_info_a_code_name": {
        "covers": ("universe",),
        "update": "交易所调整时（新股上市、退市、更名）；每日抓取一次即可",
        "rate_limit": "无公开额度；建议每日一次",
    },
    "stock_info_sh_name_code": {
        "covers": ("universe",),
        "update": "交易所调整时（新股上市、退市、更名）",
        "rate_limit": "交易所公开数据；建议每日一次",
    },
    "stock_info_sh_name_code_kcb": {
        "covers": ("universe",),
        "update": "交易所调整时",
        "rate_limit": "交易所公开数据；建议每日一次",
    },
    "stock_info_sz_name_code": {
        "covers": ("universe",),
        "update": "交易所调整时",
        "rate_limit": "交易所公开数据；建议每日一次",
    },
    "stock_info_bj_name_code": {
        "covers": ("universe",),
        "update": "交易所调整时",
        "rate_limit": "交易所公开数据；建议每日一次",
    },
    "stock_individual_info_em": {
        "covers": ("universe",),
        "update": "每日（上市时间固定，行业/市值随行情变化）",
        "rate_limit": "逐只查询；建议 ≥0.5s/次",
        "required": False,
    },
    "stock_zh_a_daily": {
        "covers": ("daily",),
        "update": "交易日收盘后（约 15:30 起）",
        "rate_limit": "无公开额度；建议单线程 ≥0.3s/次，全市场回填分批",
    },
    "stock_zh_a_hist": {
        "covers": ("daily",),
        "update": "交易日收盘后",
        "rate_limit": "未知（当前环境不可达）",
        "required": False,
    },
    "stock_zh_a_hist_tx": {
        "covers": ("daily",),
        "update": "交易日收盘后",
        "rate_limit": "无公开额度；建议单线程 ≥0.3s/次",
    },
    "stock_zh_valuation_baidu_pe": {
        "covers": ("valuation",),
        "update": "交易日（收盘后更新）",
        "rate_limit": "逐只查询；建议 ≥0.5s/次",
    },
    "stock_zh_valuation_baidu_pb": {
        "covers": ("valuation",),
        "update": "交易日（收盘后更新）",
        "rate_limit": "逐只查询；建议 ≥0.5s/次",
    },
    "stock_value_em": {
        "covers": ("valuation",),
        "update": "交易日（收盘后更新）",
        "rate_limit": "逐只查询，返回全部历史；建议 ≥0.5s/次",
    },
    "stock_zh_valuation_baidu_pe_5y": {
        "covers": ("valuation",),
        "update": "交易日（收盘后更新）",
        "rate_limit": "逐只查询；近五年序列数据量较大，建议 ≥0.5s/次",
        "required": False,
    },
    "stock_financial_abstract_ths": {
        "covers": ("financials",),
        "update": "定期报告披露后（一季报/半年报/三季报/年报）",
        "rate_limit": "按报告期批量抓取；建议 ≥0.5s/次",
    },
    "stock_financial_analysis_indicator_em": {
        "covers": ("financials",),
        "update": "定期报告披露后",
        "rate_limit": "按报告期批量抓取；建议 ≥0.5s/次",
    },
    "sw_index_first_info": {
        "covers": ("industry",),
        "update": "申万行业分类调整时（通常每年）",
        "rate_limit": "无公开额度；建议每日一次",
    },
    "sw_index_second_info": {
        "covers": ("industry",),
        "update": "申万行业分类调整时（通常每年）",
        "rate_limit": "无公开额度；建议每日一次",
    },
    "sw_index_third_cons": {
        "covers": ("industry",),
        "update": "申万行业分类调整时（通常每年）",
        "rate_limit": "按行业逐只查询；建议 ≥0.5s/次",
    },
    "stock_industry_clf_hist_sw": {
        "covers": ("industry",),
        "update": "申万行业分类调整时（通常每年）",
        "rate_limit": "全量接口，数据量约 1.3 万行；建议每日一次",
    },
    "index_hist_sw": {
        "covers": ("index",),
        "update": "交易日收盘后",
        "rate_limit": "无公开额度；建议 ≥0.3s/次",
    },
    "stock_zh_a_disclosure_report_cninfo": {
        "covers": ("announcements",),
        "update": "公告实时发布（盘后及披露时段）",
        "rate_limit": "巨潮接口易被限流/返回非 JSON；需指数退避重试，建议 ≥1s/次",
        "required": False,
    },
    "stock_notice_report": {
        "covers": ("announcements",),
        "update": "公告实时发布（盘后及披露时段）",
        "rate_limit": "按日全市场查询；建议 ≥0.5s/次",
    },
    "stock_individual_notice_report": {
        "covers": ("announcements",),
        "update": "公告实时发布（盘后及披露时段）",
        "rate_limit": "按个股查询；建议 ≥0.5s/次",
    },
    "stock_gpzy_individual_pledge_ratio_detail_em": {
        "covers": ("pledge",),
        "update": "按季度披露（以交易所/东财更新为准）",
        "rate_limit": "按个股查询；建议 ≥0.5s/次",
    },
    "stock_gpzy_pledge_ratio_em": {
        "covers": ("pledge",),
        "update": "按季度披露",
        "rate_limit": "全市场单日快照；建议每日一次",
    },
    "stock_jgdy_tj_em": {
        "covers": ("research",),
        "update": "调研记录披露后（一般 T+1）",
        "rate_limit": "按日期区间抓取；建议 ≥0.5s/次",
    },
    "stock_jgdy_detail_em": {
        "covers": ("research",),
        "update": "调研记录披露后（一般 T+1）",
        "rate_limit": "AKShare 包装按起始日全量分页，单日可达数百页；正式采集应改为按个股过滤",
        "required": False,
    },
    "em_research_visits_by_stock": {
        "covers": ("research",),
        "update": "调研记录披露后（一般 T+1）",
        "rate_limit": "按个股分页，每页 50 条；建议每只股票只取最近 1-2 页",
    },
    "stock_report_disclosure": {
        "covers": ("earnings",),
        "update": "披露日程更新时（财报季前后）",
        "rate_limit": "建议每日一次",
    },
    "index_zh_a_hist": {
        "covers": ("index",),
        "update": "交易日收盘后",
        "rate_limit": "未知（当前环境不可达）",
        "required": False,
    },
    "stock_zh_index_daily": {
        "covers": ("index",),
        "update": "交易日收盘后",
        "rate_limit": "无公开额度；建议 ≥0.3s/次",
    },
    "stock_zh_index_daily_em": {
        "covers": ("index",),
        "update": "交易日收盘后",
        "rate_limit": "未知（当前环境不可达）",
        "required": False,
    },
    "stock_profit_forecast_em": {
        "covers": ("consensus",),
        "update": "机构预测更新时（不定期）",
        "rate_limit": "按代码查询在 AKShare 1.20.6 报错；改用无参全量接口后本地过滤",
        "required": False,
    },
    "stock_profit_forecast_em_all": {
        "covers": ("consensus",),
        "update": "机构预测更新时（不定期）",
        "rate_limit": "全市场数据量大；建议每周快照",
    },
    "stock_profit_forecast_ths": {
        "covers": ("consensus",),
        "update": "机构预测更新时（不定期）",
        "rate_limit": "开源接口；建议每周快照",
    },
    "stock_balance_sheet_by_report_em": {
        "covers": ("financials",),
        "update": "定期报告披露后",
        "rate_limit": "按报告期批量抓取；建议 ≥0.5s/次",
    },
    "stock_profit_sheet_by_report_em": {
        "covers": ("financials",),
        "update": "定期报告披露后",
        "rate_limit": "按报告期批量抓取；建议 ≥0.5s/次",
    },
    "stock_cash_flow_sheet_by_report_em": {
        "covers": ("financials",),
        "update": "定期报告披露后",
        "rate_limit": "按报告期批量抓取；建议 ≥0.5s/次",
    },
    "stock_financial_report_sina_cashflow": {
        "covers": ("financials",),
        "update": "定期报告披露后",
        "rate_limit": "按报告期批量抓取；建议 ≥0.5s/次",
    },
    "stock_financial_report_sina_balance": {
        "covers": ("financials",),
        "update": "定期报告披露后",
        "rate_limit": "按报告期批量抓取；建议 ≥0.5s/次",
    },
}

PROBES = [
    replace(probe, **_METADATA.get(probe.name, {})) for probe in PROBES
]

PROBE_MAP = {probe.name: probe for probe in PROBES}


def _child_env(probe: Probe) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if probe.direct:
        env["NO_PROXY"] = "*"
        env["no_proxy"] = "*"
    return env


def run_single(name: str) -> int:
    probe = PROBE_MAP.get(name)
    if probe is None:
        print(f"未知探针：{name}", file=sys.stderr)
        return 2
    result = _run_probe(probe)
    print(RESULT_MARKER + json.dumps(result, ensure_ascii=False))
    return 0


def _run_subprocess(probe: Probe, limit: int) -> dict[str, Any]:
    started = datetime.now()
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--single", probe.name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=limit,
            env=_child_env(probe),
            check=False,
        )
        for line in reversed(completed.stdout.splitlines()):
            if line.startswith(RESULT_MARKER):
                return json.loads(line[len(RESULT_MARKER) :])
        stderr_tail = "\n".join(completed.stderr.splitlines()[-5:])
        return {
            "name": probe.name,
            "description": probe.description,
            "params": probe.params,
            "direct": probe.direct,
            "ok": False,
            "rows": None,
            "columns": [],
            "sample": [],
            "elapsed_s": round((datetime.now() - started).total_seconds(), 2),
            "error_type": "ProcessError",
            "error": f"exit={completed.returncode} {stderr_tail}"[:500],
            "truststore": False,
        }
    except subprocess.TimeoutExpired:
        return {
            "name": probe.name,
            "description": probe.description,
            "params": probe.params,
            "direct": probe.direct,
            "ok": False,
            "rows": None,
            "columns": [],
            "sample": [],
            "elapsed_s": float(limit),
            "error_type": "Timeout",
            "error": f"超过 {limit}s",
            "truststore": False,
        }


def run_parent(
    names: list[str],
    timeout: int | None,
    output: Path,
    doc: Path,
    merge: bool = False,
    workers: int = 4,
) -> int:
    def task(name: str) -> tuple[str, dict[str, Any]]:
        probe = PROBE_MAP[name]
        limit = timeout if timeout is not None else probe.timeout
        payload = _run_subprocess(probe, limit)
        status = "OK" if payload["ok"] else f"FAIL({payload['error_type']})"
        rows = payload["rows"] if payload["rows"] is not None else "-"
        print(f"[{status}] {name} rows={rows} {payload['elapsed_s']}s", flush=True)
        return name, payload

    payloads: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(task, name) for name in names]
        for future in as_completed(futures):
            name, payload = future.result()
            payloads[name] = payload
    results = [payloads[name] for name in names]

    if merge and output.exists():
        previous = json.loads(output.read_text(encoding="utf-8"))
        merged = {item["name"]: item for item in previous}
        merged.update({item["name"]: item for item in results})
        results = [merged[probe.name] for probe in PROBES if probe.name in merged]

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    ok_count = sum(1 for item in results if item["ok"])
    print(f"\n{ok_count}/{len(results)} 接口可用；结果已写入 {output}")
    _write_doc(results, doc, datetime.now().isoformat(timespec="seconds"))
    uncovered = [
        requirement.title
        for requirement in DATA_REQUIREMENTS
        if _coverage_status(results, requirement.key) != "可用"
    ]
    if uncovered:
        print("以下数据项尚无可用接口：" + "；".join(uncovered))
        return 1
    print("5.1 全部数据项均有可用接口。")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty():
            with contextlib.suppress(AttributeError, ValueError):
                stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="探测 AKShare 接口可用性")
    parser.add_argument("--list", action="store_true", help="列出全部探针")
    parser.add_argument("--all", action="store_true", help="运行全部探针")
    parser.add_argument("--only", default="", help="逗号分隔的探针名")
    parser.add_argument("--single", default="", help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=int, default=None, help="覆盖单个探针超时秒数")
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="结果 JSON 输出路径"
    )
    parser.add_argument(
        "--doc",
        type=Path,
        default=PROJECT_ROOT / "docs" / "data_sources.md",
        help="Markdown 文档输出路径",
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="不联网，仅用已有 JSON 重新生成文档",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="与已有 JSON 结果合并（用于补测单个探针）",
    )
    parser.add_argument(
        "--workers", type=int, default=4, help="并发探测的子进程数（默认 4）"
    )
    args = parser.parse_args()

    if args.single:
        return run_single(args.single)
    if args.list:
        for probe in PROBES:
            print(f"{probe.name}\t{probe.description}")
        return 0
    if args.render_only:
        if not args.output.exists():
            parser.error(f"结果文件不存在：{args.output}")
        results = json.loads(args.output.read_text(encoding="utf-8"))
        _write_doc(results, args.doc, datetime.now().isoformat(timespec="seconds"))
        return 0
    if args.all:
        names = [probe.name for probe in PROBES]
    elif args.only:
        names = [item.strip() for item in args.only.split(",") if item.strip()]
        unknown = [name for name in names if name not in PROBE_MAP]
        if unknown:
            parser.error(f"未知探针：{', '.join(unknown)}")
    else:
        # 无参数时执行全部探针并生成文档（任务书 T0.3 的验收命令）
        names = [probe.name for probe in PROBES]
    return run_parent(
        names,
        args.timeout,
        args.output,
        args.doc,
        merge=args.merge,
        workers=args.workers,
    )


if __name__ == "__main__":
    sys.exit(main())
