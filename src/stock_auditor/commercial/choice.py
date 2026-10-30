"""东方财富 Choice（EmQuantAPI）适配器。

字段名与周期参数集中在模块顶部；客户开通账号后先用探测脚本确认
（任务书 5.1 的要求），如有差异只改这里。缺少账号或插件时返回「未配置」。
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import structlog

from stock_auditor.commercial.base import (
    CommercialError,
    CommercialSource,
    FinancialRecord,
)
from stock_auditor.ingest.common import (
    clean_number,
    exchange_prefix,
    frame_records,
    normalize_code,
    to_date,
)

log = structlog.get_logger(__name__)

_REVENUE_FIELDS = ("MAINOPERINCOME", "OPERATEINCOME", "TOTALOPERATEINCOME")
_NET_PROFIT_FIELDS = ("PARENTNETPROFIT", "NETPROFITPARENT")
_OCF_FIELDS = ("NETCASHOPERATE", "NETCASHFLOWOPERATE")
_DATE_FIELDS = ("DATES", "REPORTDATE", "REPORT_DATE", "ENDDATE", "日期")
_INDICATORS = ",".join((*_REVENUE_FIELDS[:1], *_NET_PROFIT_FIELDS[:1], *_OCF_FIELDS[:1]))
_CSD_OPTIONS = "period=4,adjustflag=1,curtype=1,order=1,market=CNSESH"


def _choice_symbol(code: str) -> str:
    return f"{normalize_code(code)}.{exchange_prefix(code).upper()}"


def _first_number(record: dict[str, Any], fields: Sequence[str]) -> float | None:
    for field in fields:
        value = clean_number(record.get(field))
        if value is not None:
            return value
    return None


def _first_date(record: dict[str, Any]) -> date | None:
    for field in _DATE_FIELDS:
        value = to_date(record.get(field))
        if value is not None:
            return value
    return None


def _result_frame(result: Any, symbol: str) -> Any:
    error_code = getattr(result, "ErrorCode", 0)
    if error_code not in (0, None):
        message = getattr(result, "ErrorMsg", str(error_code))
        raise CommercialError(f"Choice 返回错误 {error_code}: {message}")
    data = getattr(result, "Data", None)
    if data is None and isinstance(result, dict):
        data = result.get("Data")
    if data is None:
        raise CommercialError("Choice 返回缺少 Data 字段")
    if isinstance(data, dict):
        data = data.get(symbol)
    return data


class ChoiceSource(CommercialSource):
    """Choice EmQuantAPI 实现；仅 Windows 插件，调用失败抛 ``CommercialError``。"""

    name = "choice"

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._api: Any = None

    @classmethod
    def from_env(cls) -> ChoiceSource:
        return cls(
            username=os.environ.get("COMMERCIAL_USERNAME", ""),
            password=os.environ.get("COMMERCIAL_PASSWORD", ""),
        )

    @property
    def _module_available(self) -> bool:
        return importlib.util.find_spec("EmQuantAPI") is not None

    @property
    def configured(self) -> bool:
        return bool(self._username and self._password) and self._module_available

    @property
    def status(self) -> str:
        missing: list[str] = []
        if not self._username or not self._password:
            missing.append("缺少 COMMERCIAL_USERNAME/COMMERCIAL_PASSWORD")
        if not self._module_available:
            missing.append("未安装 EmQuantAPI")
        if missing:
            return "未配置：" + "；".join(missing)
        return "已配置"

    def _ensure_api(self) -> Any:
        if self._api is not None:
            return self._api
        try:
            from EmQuantAPI import c
        except ImportError as exc:
            raise CommercialError("EmQuantAPI 未安装") from exc
        result = c.start("ForceLogin=1", self._username, self._password)
        if isinstance(result, int) and result != 0:
            raise CommercialError(f"Choice 登录失败，返回码 {result}")
        self._api = c
        return c

    def _fetch_one(self, api: Any, code: str, periods: int) -> list[FinancialRecord]:
        symbol = _choice_symbol(code)
        end = date.today()
        start = end - timedelta(days=periods * 100 + 200)
        result = api.csd(
            symbol,
            _INDICATORS,
            start.isoformat(),
            end.isoformat(),
            _CSD_OPTIONS,
        )
        data = _result_frame(result, symbol)
        if data is None:
            return []

        records: list[FinancialRecord] = []
        for row in frame_records(data):
            period = _first_date(row)
            if period is None:
                continue
            revenue = _first_number(row, _REVENUE_FIELDS)
            net_profit = _first_number(row, _NET_PROFIT_FIELDS)
            ocf = _first_number(row, _OCF_FIELDS)
            if revenue is None and net_profit is None and ocf is None:
                continue
            records.append(
                FinancialRecord(
                    code=normalize_code(code),
                    report_period=period,
                    revenue=revenue,
                    net_profit_parent=net_profit,
                    ocf=ocf,
                )
            )
        records.sort(key=lambda item: item.report_period, reverse=True)
        return records[:periods]

    def fetch_financials(
        self,
        codes: Sequence[str],
        periods: int,
    ) -> list[FinancialRecord]:
        if not self.configured:
            return []
        api = self._ensure_api()
        records: list[FinancialRecord] = []
        for raw_code in codes:
            code = normalize_code(raw_code)
            try:
                records.extend(self._fetch_one(api, code, periods))
            except CommercialError:
                raise
            except Exception as exc:  # noqa: BLE001 - 单只失败不阻塞整批
                log.error("commercial.choice.failed", code=code, error=str(exc))
        log.info("commercial.choice.fetched", rows=len(records), codes=len(codes))
        return records
