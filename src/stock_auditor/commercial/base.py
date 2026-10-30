"""商业数据源适配器接口。

商业源（Choice / iFinD）是可选插件：没有账号或插件未安装时，适配器必须
返回「未配置」而不是抛错，主流程照常运行，只是跳过交叉验证。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date


class CommercialError(RuntimeError):
    """商业源已配置但调用失败。"""


@dataclass(frozen=True)
class FinancialRecord:
    """商业源的一条报告期财务数据，金额单位为元。"""

    code: str
    report_period: date
    revenue: float | None
    net_profit_parent: float | None
    ocf: float | None


class CommercialSource(ABC):
    """商业源统一接口；上层只依赖这一层。"""

    name: str

    @property
    @abstractmethod
    def configured(self) -> bool:
        """账号与插件都就绪时为 True。"""

    @property
    @abstractmethod
    def status(self) -> str:
        """供日志与 ``sa doctor`` 展示的状态文本。"""

    @abstractmethod
    def fetch_financials(
        self,
        codes: Sequence[str],
        periods: int,
    ) -> list[FinancialRecord]:
        """返回每只股票最近 ``periods`` 个报告期的财务数据。"""


@dataclass(frozen=True)
class UnconfiguredSource(CommercialSource):
    """未启用或缺少账号时的占位实现，所有调用都安全返回空。"""

    reason: str = "商业数据源未启用"
    name: str = "unconfigured"

    @property
    def configured(self) -> bool:
        return False

    @property
    def status(self) -> str:
        return f"未配置：{self.reason}"

    def fetch_financials(
        self,
        codes: Sequence[str],
        periods: int,
    ) -> list[FinancialRecord]:
        del codes, periods
        return []
