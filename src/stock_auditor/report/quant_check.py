"""T1.6 量化校准检查报告：7 只校准股的过滤结果与量化分。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from stock_auditor import paths
from stock_auditor.domain import FilterResult
from stock_auditor.scoring.fundamental import FundamentalResult
from stock_auditor.scoring.momentum import MomentumResult

CALIBRATION_CODES: tuple[str, ...] = (
    "002773",
    "002185",
    "002774",
    "002354",
    "002724",
    "603528",
    "600664",
)

REPORT_FILENAME = "quant_check.md"


@dataclass(frozen=True)
class QuantCheckRow:
    code: str
    name: str | None
    filter_result: FilterResult | None
    fundamental: FundamentalResult | None
    momentum: MomentumResult | None
    data_flag: str | None
    pool_source: str | None


def _num(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.2%}"


def _filter_text(row: QuantCheckRow) -> str:
    if row.filter_result is None:
        return "未在股票池"
    return "通过" if row.filter_result.passed else "剔除"


def _table_row(row: QuantCheckRow) -> str:
    fundamental = row.fundamental.total if row.fundamental is not None else None
    momentum = row.momentum.score if row.momentum is not None else None
    quant = (
        fundamental + momentum
        if fundamental is not None and momentum is not None
        else None
    )
    return "| " + " | ".join(
        [
            row.code,
            row.name or "—",
            _filter_text(row),
            _num(fundamental),
            _num(momentum),
            _num(quant),
            row.data_flag or "—",
            row.pool_source or "—",
        ]
    ) + " |"


def _detail(row: QuantCheckRow) -> list[str]:
    lines = [f"### {row.code} {row.name or ''}".rstrip(), ""]
    if row.filter_result is None:
        lines.append("- 过滤：该代码不在股票池中，未参与本次量化。")
    else:
        lines.append(f"- 过滤：{_filter_text(row)}")
        if row.filter_result.reasons:
            lines.append(f"- 剔除原因：{'；'.join(row.filter_result.reasons)}")

    if row.fundamental is not None:
        result = row.fundamental
        lines.append(
            f"- 基本面：{result.total:.1f} "
            f"（盈利 {result.profitability:.1f} / 成长 {result.growth:.1f} / "
            f"估值 {result.valuation:.1f} / 健康 {result.health:.1f}）"
        )
        if result.tags:
            lines.append(f"- 基本面标签：{'、'.join(result.tags)}")
    else:
        lines.append("- 基本面：未评分（未通过 Stage 0 或未进入 LLM 池）")

    if row.momentum is not None:
        result = row.momentum
        raw = result.raw
        lines.append(
            f"- 动量：{result.score:.1f}（基础 {result.base:.1f}，"
            f"扣分 {result.penalty:.1f}）"
        )
        lines.append(
            f"- 动量原始值：r5 {_pct(raw.get('r5'))}，r20 {_pct(raw.get('r20'))}，"
            f"偏离 20 日均线 {_pct(raw.get('dev20'))}"
        )
        if result.tags:
            lines.append(f"- 动量标签：{'、'.join(result.tags)}")
    else:
        lines.append("- 动量：未评分")

    lines.append(f"- 数据标记：{row.data_flag or '—'}")
    lines.append(f"- LLM 池来源：{row.pool_source or '未入池'}")
    lines.append("")
    return lines


def render_quant_check(
    *,
    run_id: str,
    as_of: date,
    rows: Sequence[QuantCheckRow],
    universe_count: int,
    stage0_passed: int,
    hard_veto: int,
    pool_count: int,
) -> str:
    lines = [
        "# 量化校准检查",
        "",
        f"- 运行编号：{run_id}",
        f"- 数据日期：{as_of.isoformat()}",
        f"- 股票池：{universe_count} 只；Stage 0 通过：{stage0_passed} 只；"
        f"硬 Veto：{hard_veto} 只；LLM 池：{pool_count} 只",
        "",
        "| 代码 | 名称 | 过滤结果 | 基本面 | 动量 | 量化合计 | 数据标记 | LLM 池来源 |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    lines.extend(_table_row(row) for row in rows)
    lines.append("")
    for row in rows:
        lines.extend(_detail(row))
    return "\n".join(lines)


def write_quant_check(
    *,
    run_id: str,
    as_of: date,
    rows: Sequence[QuantCheckRow],
    universe_count: int,
    stage0_passed: int,
    hard_veto: int,
    pool_count: int,
    path: Path | None = None,
) -> Path:
    target = Path(path) if path is not None else paths.reports_dir() / REPORT_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    content = render_quant_check(
        run_id=run_id,
        as_of=as_of,
        rows=rows,
        universe_count=universe_count,
        stage0_passed=stage0_passed,
        hard_veto=hard_veto,
        pool_count=pool_count,
    )
    target.write_text(content, encoding="utf-8")
    return target
