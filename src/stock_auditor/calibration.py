"""7 只校准股的完整 Tier-1 → Tier-2 对照（任务书 12.7 节）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import duckdb

from stock_auditor.config import Settings, load_industry_peg
from stock_auditor.llm.audit import LlmCompleter, audit_stock
from stock_auditor.pipeline.loader import load_universe
from stock_auditor.pipeline.run_context import RunContext
from stock_auditor.scoring import score_fundamentals, score_momentum


@dataclass(frozen=True)
class CalibrationStock:
    code: str
    name: str
    low: int
    high: int
    label: str


CALIBRATION_STOCKS: tuple[CalibrationStock, ...] = (
    CalibrationStock("002773", "康弘药业", 36, 40, "正面标杆"),
    CalibrationStock("002185", "华天科技", 36, 40, "正面标杆"),
    CalibrationStock("002774", "快意电梯", 25, 35, "潜力观察"),
    CalibrationStock("002354", "天娱数科", 25, 35, "潜力观察"),
    CalibrationStock("002724", "海洋王", 25, 35, "潜力观察"),
    CalibrationStock("603528", "多伦科技", 25, 35, "潜力观察"),
    CalibrationStock("600664", "哈药股份", 0, 10, "反面炒作"),
)
CALIBRATION_CODES: tuple[str, ...] = tuple(
    stock.code for stock in CALIBRATION_STOCKS
)
PASS_THRESHOLD = 5


@dataclass(frozen=True)
class CalibrationRow:
    code: str
    name: str
    low: int
    high: int
    label: str
    status: str
    score: int | None = None
    tier: str | None = None
    error: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def in_range(self) -> bool:
        return self.score is not None and self.low <= self.score <= self.high


@dataclass(frozen=True)
class CalibrationResult:
    run_id: str
    as_of: date
    rows: tuple[CalibrationRow, ...] = ()
    warnings: list[str] = field(default_factory=list)

    @property
    def in_range_count(self) -> int:
        return sum(1 for row in self.rows if row.in_range)

    @property
    def failed_count(self) -> int:
        return sum(1 for row in self.rows if row.status != "ok")

    @property
    def passed(self) -> bool:
        return self.in_range_count >= PASS_THRESHOLD


def run_calibration(
    connection: duckdb.DuckDBPyConnection,
    settings: Settings,
    *,
    client: LlmCompleter,
    as_of: date | None = None,
    prompt_dir=None,
) -> CalibrationResult:
    run_date = as_of or date.today()
    universe = load_universe(
        connection,
        as_of=run_date,
        codes=list(CALIBRATION_CODES),
    )
    present = [data for data in universe.data.values() if data.stock.code in CALIBRATION_CODES]

    fundamentals = (
        score_fundamentals(present, settings, load_industry_peg(), run_date)
        if present
        else {}
    )
    momentum = {
        data.stock.code: score_momentum(data.quotes, settings) for data in present
    }

    context = RunContext.start("calibrate")
    context.save(connection)
    rows: list[CalibrationRow] = []
    warnings: list[str] = []
    for spec in CALIBRATION_STOCKS:
        data = universe.data.get(spec.code)
        if data is None:
            rows.append(
                CalibrationRow(
                    code=spec.code,
                    name=spec.name,
                    low=spec.low,
                    high=spec.high,
                    label=spec.label,
                    status="missing",
                    error="数据库中没有该股票的数据",
                )
            )
            continue
        audit = audit_stock(
            connection,
            client,
            context.run_id,
            data=data,
            settings=settings,
            as_of=run_date,
            fundamental=fundamentals.get(spec.code),
            momentum=momentum.get(spec.code),
            prompt_dir=prompt_dir,
        )
        warnings.extend(audit.warnings)
        score = audit.tier2.score if audit.tier2 is not None else None
        rows.append(
            CalibrationRow(
                code=spec.code,
                name=spec.name,
                low=spec.low,
                high=spec.high,
                label=spec.label,
                status=audit.status,
                score=score.score if score is not None else None,
                tier=score.tier if score is not None else None,
                error=audit.tier2.error if audit.tier2 and audit.tier2.error else (
                    audit.tier1.error if audit.tier1.error else None
                ),
                warnings=audit.warnings,
            )
        )

    context.finish()
    context.save(connection)
    return CalibrationResult(
        run_id=context.run_id,
        as_of=run_date,
        rows=tuple(rows),
        warnings=warnings,
    )
