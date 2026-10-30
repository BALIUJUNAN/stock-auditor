"""生成 Tier-2 输入的硬指标表（任务书 12.4 节）。"""

from __future__ import annotations

from stock_auditor.scoring import FundamentalResult, MomentumResult

_MISSING = "缺失"


def _value(value: float | None) -> str:
    return _MISSING if value is None else f"{value:.4g}"


def build_metric_text(
    *,
    code: str,
    name: str,
    fundamental: FundamentalResult | None,
    momentum: MomentumResult | None,
) -> str:
    lines = [f"股票：{name}（{code}）"]
    if fundamental is None:
        lines.append("量化评分：缺失")
    else:
        lines.append(
            "基本面："
            f"{fundamental.total:.1f}/40（盈利 {fundamental.profitability:.1f}、"
            f"成长 {fundamental.growth:.1f}、估值 {fundamental.valuation:.1f}、"
            f"健康 {fundamental.health:.1f}）"
        )
        for key, value in fundamental.raw_values.items():
            lines.append(f"  - {key}：{_value(value)}")
        for key, value in fundamental.percentiles.items():
            lines.append(f"  - 分位 {key}：{_value(value)}")
        if fundamental.tags:
            lines.append(f"  - 标签：{'、'.join(fundamental.tags)}")
    if momentum is not None:
        lines.append(
            f"动量：{momentum.score:.1f}/20（基础 {momentum.base:.1f}、"
            f"扣分 {momentum.penalty:.1f}）"
        )
        if momentum.tags:
            lines.append(f"  - 动量标签：{'、'.join(momentum.tags)}")
    return "\n".join(lines)
