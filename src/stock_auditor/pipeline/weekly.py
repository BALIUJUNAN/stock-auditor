"""周日流水线 S1~S8：数据、量化、模型审计、汇总与周报。

每一步完成后写 ``run_log.step_status``；``--resume`` 从最近一次未成功的
运行继续，``--resume RUN_ID`` 从指定运行继续，已完成的步骤直接读取数据库结果。
同一流水线用文件锁防止并发。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

import duckdb
import structlog

from stock_auditor import paths
from stock_auditor.commercial.base import CommercialError, FinancialRecord
from stock_auditor.commercial.cross_validation import cross_validate
from stock_auditor.commercial.factory import create_commercial_source
from stock_auditor.config import Settings, load_industry_peg
from stock_auditor.domain import FilterResult, StockData
from stock_auditor.filters.service import store_filter_results, store_veto_events
from stock_auditor.filters.stage0 import evaluate_stage0
from stock_auditor.filters.veto import (
    VetoEvent,
    check_hard_veto,
    check_soft_downgrade,
)
from stock_auditor.funnel import (
    PoolCandidate,
    PoolEntry,
    build_llm_pool,
    load_watchlist,
    store_llm_pool,
)
from stock_auditor.ingest import run_ingest
from stock_auditor.ingest.announcements import backfill_announcement_text
from stock_auditor.ingest.common import DataClient
from stock_auditor.llm.audit import (
    LlmCompleter,
    Tier1Outcome,
    run_tier1,
    run_tier2,
    store_tier1,
    store_tier2,
)
from stock_auditor.llm.client import (
    LlmClient,
    LlmNotConfiguredError,
    LlmUsage,
)
from stock_auditor.llm.materials import (
    assemble_materials,
    materials_from_announcements,
)
from stock_auditor.llm.metrics import build_metric_text
from stock_auditor.llm.schemas import Tier1Dossier, Tier2Score
from stock_auditor.pipeline.loader import UniverseData, load_universe
from stock_auditor.pipeline.lock import FileLock
from stock_auditor.pipeline.run_context import RunContext
from stock_auditor.report.quant_check import (
    CALIBRATION_CODES,
    QuantCheckRow,
    write_quant_check,
)
from stock_auditor.report.weekly import WeeklyReport, build_weekly_report
from stock_auditor.scoring import (
    CompositeResult,
    FundamentalResult,
    MomentumResult,
    QuantScore,
    compose_score,
    score_fundamentals,
    score_momentum,
    store_final_scores,
    store_quant_scores,
)

log = structlog.get_logger(__name__)

PIPELINE = "weekly"
STEPS: tuple[str, ...] = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")


@dataclass(frozen=True)
class WeeklyResult:
    run_id: str
    as_of: date
    universe_count: int
    stage0_passed_count: int
    hard_veto_count: int
    filter_results: dict[str, FilterResult] = field(default_factory=dict)
    veto_events: dict[str, list[VetoEvent]] = field(default_factory=dict)
    fundamentals: dict[str, FundamentalResult] = field(default_factory=dict)
    momentum: dict[str, MomentumResult] = field(default_factory=dict)
    data_flags: dict[str, str | None] = field(default_factory=dict)
    pool: list[PoolEntry] = field(default_factory=list)
    quant_check_path: Path | None = None
    final_scores: dict[str, CompositeResult] = field(default_factory=dict)
    audit_ok_count: int = 0
    audit_failed_count: int = 0
    report_path: Path | None = None
    chart_path: Path | None = None
    llm_skipped: bool = False
    llm_skip_reason: str | None = None


def _parse_until(until: str) -> str:
    step = until.strip().upper()
    if step not in STEPS:
        raise ValueError(f"不支持的步骤 {until!r}；可选 {', '.join(STEPS)}")
    return step


def _reached(step: str, target: str) -> bool:
    return STEPS.index(step) <= STEPS.index(target)


def _run_step(
    context: RunContext,
    connection: duckdb.DuckDBPyConnection,
    name: str,
    func: Callable[[], object],
) -> object:
    context.begin_step(name)
    context.save(connection)
    try:
        result = func()
    except Exception as exc:
        context.fail_step(name, str(exc))
        context.save(connection)
        raise
    context.complete_step(name)
    context.save(connection)
    return result


def _state_path(run_id: str) -> Path:
    return paths.state_dir() / f"{run_id}.json"


def _write_state(run_id: str, *, as_of: date, codes: Sequence[str] | None) -> None:
    path = _state_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"as_of": as_of.isoformat(), "codes": list(codes) if codes else None},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _read_state(run_id: str) -> tuple[date | None, list[str] | None]:
    path = _state_path(run_id)
    if not path.is_file():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    try:
        as_of = date.fromisoformat(str(data["as_of"]))
    except (KeyError, TypeError, ValueError):
        as_of = None
    codes = data.get("codes")
    return as_of, [str(code) for code in codes] if codes else None


def _restore_context(
    connection: duckdb.DuckDBPyConnection,
    run_id: str | None = None,
) -> RunContext:
    if run_id:
        row = connection.execute(
            "SELECT run_id, pipeline, started_at, status, step_status, "
            "llm_tokens, llm_cost FROM run_log "
            "WHERE run_id = ? AND pipeline = ?",
            [run_id, PIPELINE],
        ).fetchone()
        if row is None:
            raise ValueError(f"找不到周流水线运行记录：{run_id}")
        if str(row[3]) == "success":
            raise ValueError(f"运行 {run_id} 已完成，无需续跑")
    else:
        row = connection.execute(
            "SELECT run_id, pipeline, started_at, status, step_status, "
            "llm_tokens, llm_cost FROM run_log "
            "WHERE pipeline = ? AND status <> 'success' "
            "ORDER BY started_at DESC LIMIT 1",
            [PIPELINE],
        ).fetchone()
        if row is None:
            raise ValueError("没有可续跑的周流水线运行记录")
    run_id, pipeline, started_at, _, step_status, tokens, cost = row
    try:
        steps = json.loads(step_status) if step_status else {}
    except json.JSONDecodeError:
        steps = {}
    return RunContext(
        run_id=str(run_id),
        pipeline=str(pipeline),
        started_at=started_at,
        status="running",
        step_status={str(key): str(value) for key, value in dict(steps).items()},
        llm_tokens=int(tokens or 0),
        llm_cost=float(cost or 0.0),
    )


def _stage0(
    universe: UniverseData,
    settings: Settings,
    as_of: date,
) -> tuple[dict[str, FilterResult], dict[str, list[VetoEvent]]]:
    results: dict[str, FilterResult] = {}
    vetoes: dict[str, list[VetoEvent]] = {}
    for code, data in universe.data.items():
        base = evaluate_stage0(data.stock, data.quotes, settings, as_of)
        hard = check_hard_veto(data, settings, as_of)
        reasons = list(base.reasons)
        reasons.extend(f"硬 Veto：{event.rule}（{event.detail}）" for event in hard)
        results[code] = FilterResult(
            code=code,
            passed=base.passed and not hard,
            reasons=reasons,
        )
        if hard:
            vetoes[code] = hard
    return results, vetoes


def _data_flags(
    data_list: Sequence[StockData],
    settings: Settings,
) -> dict[str, str | None]:
    cv = settings.data_quality.cross_validation
    codes = [data.stock.code for data in data_list]
    source = create_commercial_source(settings)
    if not source.configured:
        return {code: cv.missing_label for code in codes}
    try:
        commercial = source.fetch_financials(codes, settings.ingest.financial_periods)
    except CommercialError as exc:
        log.warning("pipeline.cross_validation_failed", error=str(exc))
        return {code: cv.missing_label for code in codes}

    open_records = [
        FinancialRecord(
            code=data.stock.code,
            report_period=row.report_period,
            revenue=row.revenue,
            net_profit_parent=row.net_profit_parent,
            ocf=row.ocf,
        )
        for data in data_list
        for row in data.financials
    ]
    return cross_validate(
        codes,
        open_records,
        commercial,
        max_deviation=cv.max_deviation,
        missing_label=cv.missing_label,
        suspect_label=cv.suspect_label,
    )


def _score(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
    data_list: Sequence[StockData],
    settings: Settings,
    as_of: date,
    peer_data: Sequence[StockData] | None = None,
) -> tuple[
    dict[str, FundamentalResult],
    dict[str, MomentumResult],
    dict[str, str | None],
]:
    if not data_list:
        return {}, {}, {}
    peg_rules = load_industry_peg()
    fundamentals = score_fundamentals(data_list, settings, peg_rules, as_of, peer_data=peer_data)
    momentum = {data.stock.code: score_momentum(data.quotes, settings) for data in data_list}
    data_flags = _data_flags(data_list, settings)

    rows = []
    for data in data_list:
        code = data.stock.code
        fund = fundamentals[code]
        mom = momentum[code]
        raw_values = dict(fund.raw_values)
        raw_values.update({f"momentum_{key}": value for key, value in mom.raw.items()})
        rows.append(
            QuantScore(
                code=code,
                fundamental=fund.total,
                momentum=mom.score,
                raw_values=raw_values,
                industry_percentiles=dict(fund.percentiles),
                scores={
                    "profitability": fund.profitability,
                    "growth": fund.growth,
                    "valuation": fund.valuation,
                    "health": fund.health,
                    "momentum_base": mom.base,
                    "momentum_penalty": mom.penalty,
                },
                is_imputed=dict(fund.imputed),
                tags=[*fund.tags, *mom.tags],
                data_flag=data_flags.get(code),
            )
        )
    store_quant_scores(connection, run_id, rows)
    return fundamentals, momentum, data_flags


def _llm_pool(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
    universe: UniverseData,
    settings: Settings,
    as_of: date,
    filter_results: dict[str, FilterResult],
    veto_events: dict[str, list[VetoEvent]],
    fundamentals: dict[str, FundamentalResult],
    momentum: dict[str, MomentumResult],
    data_flags: dict[str, str | None],
) -> list[PoolEntry]:
    watchlist = load_watchlist(max_entries=settings.funnel.watchlist_max)
    candidates = []
    for code, data in universe.data.items():
        fund = fundamentals.get(code)
        mom = momentum.get(code)
        candidates.append(
            PoolCandidate(
                data=data,
                fundamental=fund.total if fund is not None else 0.0,
                momentum=mom.score if mom is not None else 0.0,
                stage0_passed=filter_results[code].passed,
                hard_veto=bool(veto_events.get(code)),
                data_flag=data_flags.get(code),
            )
        )
    entries = build_llm_pool(
        candidates,
        settings,
        as_of=as_of,
        watchlist_codes=watchlist.codes,
    )
    store_llm_pool(connection, run_id, entries)
    return entries


def _quant_check_rows(
    universe: UniverseData,
    filter_results: dict[str, FilterResult],
    fundamentals: dict[str, FundamentalResult],
    momentum: dict[str, MomentumResult],
    data_flags: dict[str, str | None],
    pool: Sequence[PoolEntry],
) -> list[QuantCheckRow]:
    sources = {entry.code: entry.source for entry in pool}
    rows = []
    for code in CALIBRATION_CODES:
        data = universe.data.get(code)
        rows.append(
            QuantCheckRow(
                code=code,
                name=data.stock.name if data is not None else None,
                filter_result=filter_results.get(code),
                fundamental=fundamentals.get(code),
                momentum=momentum.get(code),
                data_flag=data_flags.get(code),
                pool_source=sources.get(code),
            )
        )
    return rows


def _load_filter_results(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
) -> dict[str, FilterResult]:
    results: dict[str, FilterResult] = {}
    for code, passed, reasons in connection.execute(
        "SELECT code, passed, reasons FROM filter_log WHERE run_id = ?",
        [run_id],
    ).fetchall():
        try:
            parsed = json.loads(reasons) if reasons else []
        except json.JSONDecodeError:
            parsed = []
        results[str(code)] = FilterResult(
            code=str(code),
            passed=bool(passed),
            reasons=[str(reason) for reason in parsed],
        )
    return results


def _load_veto_events(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
) -> dict[str, list[VetoEvent]]:
    events: dict[str, list[VetoEvent]] = {}
    for code, rule, level, detail, penalty in connection.execute(
        "SELECT code, rule, level, detail, penalty FROM veto_events WHERE run_id = ?",
        [run_id],
    ).fetchall():
        events.setdefault(str(code), []).append(
            VetoEvent(
                rule=str(rule),
                level=str(level),  # type: ignore[arg-type]
                detail=str(detail or ""),
                penalty=float(penalty or 0.0),
            )
        )
    return events


def load_quant_state(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
) -> tuple[
    dict[str, FundamentalResult],
    dict[str, MomentumResult],
    dict[str, str | None],
]:
    fundamentals: dict[str, FundamentalResult] = {}
    momentum: dict[str, MomentumResult] = {}
    data_flags: dict[str, str | None] = {}
    for row in connection.execute(
        "SELECT code, raw_values, industry_percentiles, scores, is_imputed, "
        "fundamental, momentum, tags, data_flag FROM quant_scores "
        "WHERE run_id = ?",
        [run_id],
    ).fetchall():
        code = str(row[0])
        raw = _json_dict(row[1])
        percentiles = _json_dict(row[2])
        scores = _json_dict(row[3])
        imputed = _json_dict(row[4])
        fundamental = float(row[5] or 0.0)
        momentum_score = float(row[6] or 0.0)
        tags = _json_list(row[7])
        data_flags[code] = row[8]
        fundamentals[code] = FundamentalResult(
            code=code,
            total=fundamental,
            profitability=float(scores.get("profitability", 0.0) or 0.0),
            growth=float(scores.get("growth", 0.0) or 0.0),
            valuation=float(scores.get("valuation", 0.0) or 0.0),
            health=float(scores.get("health", 0.0) or 0.0),
            raw_values=raw,
            percentiles=percentiles,
            imputed={key: bool(value) for key, value in imputed.items()},
            tags=tags,
        )
        momentum[code] = MomentumResult(
            score=momentum_score,
            base=float(scores.get("momentum_base", momentum_score) or 0.0),
            penalty=float(scores.get("momentum_penalty", 0.0) or 0.0),
            tags=[],
            raw={
                key.removeprefix("momentum_"): value
                for key, value in raw.items()
                if key.startswith("momentum_")
            },
        )
    return fundamentals, momentum, data_flags


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _load_pool(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
) -> list[PoolEntry]:
    return [
        PoolEntry(code=str(code), source=str(source))
        for code, source in connection.execute(
            "SELECT code, source FROM llm_pool WHERE run_id = ? ORDER BY code",
            [run_id],
        ).fetchall()
    ]


def _load_tier1_dossiers(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
) -> dict[str, Tier1Dossier]:
    dossiers: dict[str, Tier1Dossier] = {}
    for code, payload in connection.execute(
        "SELECT code, payload FROM tier1_dossiers WHERE run_id = ? AND status = 'ok'",
        [run_id],
    ).fetchall():
        data = _json_dict(payload)
        if data:
            dossiers[str(code)] = Tier1Dossier.model_validate(data)
    return dossiers


def _load_tier2_scores(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
) -> dict[str, Tier2Score]:
    scores: dict[str, Tier2Score] = {}
    for code, payload in connection.execute(
        "SELECT code, payload FROM tier2_scores WHERE run_id = ? AND status = 'ok'",
        [run_id],
    ).fetchall():
        data = _json_dict(payload)
        if data:
            scores[str(code)] = Tier2Score.model_validate(data)
    return scores


def _load_final_scores(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
) -> dict[str, CompositeResult]:
    results: dict[str, CompositeResult] = {}
    for row in connection.execute(
        "SELECT code, raw_total, final_total, stars, is_yellow, is_veto "
        "FROM final_scores WHERE run_id = ?",
        [run_id],
    ).fetchall():
        results[str(row[0])] = CompositeResult(
            raw_total=row[1],
            final_total=row[2],
            quant_total=0.0,
            stars=row[3],
            is_yellow=bool(row[4]),
            is_veto=bool(row[5]),
        )
    return results


def _ensure_client(
    client: LlmCompleter | None,
    settings: Settings,
) -> LlmCompleter:
    if client is not None:
        return client
    return LlmClient(settings)


def _tier1_step(
    connection: duckdb.DuckDBPyConnection,
    context: RunContext,
    universe: UniverseData,
    settings: Settings,
    as_of: date,
    pool: Sequence[PoolEntry],
    client: LlmCompleter,
) -> dict[str, Tier1Dossier]:
    dossiers = _load_tier1_dossiers(connection, context.run_id)
    for entry in pool:
        if entry.code in dossiers:
            continue
        data = universe.data.get(entry.code)
        if data is None:
            continue
        materials = assemble_materials(
            materials_from_announcements(data.announcements),
            settings,
            as_of=as_of,
        )
        if not materials.items:
            outcome = Tier1Outcome(
                dossier=None,
                status="audit_failed",
                model=settings.llm.tier1_model,
                prompt_version="",
                input_hash="",
                usage=LlmUsage(),
                error="近窗口内无可用材料",
            )
        else:
            outcome = run_tier1(
                client,
                stock_code=entry.code,
                stock_name=data.stock.name,
                materials=materials,
                settings=settings,
                as_of=as_of,
            )
        store_tier1(connection, context.run_id, entry.code, outcome)
        context.add_usage(outcome.usage.total_tokens, outcome.usage.cost)
        if outcome.dossier is not None:
            dossiers[entry.code] = outcome.dossier
    return dossiers


def _tier2_step(
    connection: duckdb.DuckDBPyConnection,
    context: RunContext,
    universe: UniverseData,
    settings: Settings,
    as_of: date,
    pool: Sequence[PoolEntry],
    dossiers: dict[str, Tier1Dossier],
    fundamentals: dict[str, FundamentalResult],
    momentum: dict[str, MomentumResult],
    client: LlmCompleter,
) -> dict[str, Tier2Score]:
    scores = _load_tier2_scores(connection, context.run_id)
    for entry in pool:
        if entry.code in scores:
            continue
        dossier = dossiers.get(entry.code)
        data = universe.data.get(entry.code)
        if dossier is None or data is None:
            continue
        metric_text = build_metric_text(
            code=entry.code,
            name=data.stock.name,
            fundamental=fundamentals.get(entry.code),
            momentum=momentum.get(entry.code),
        )
        outcome = run_tier2(
            client,
            stock_code=entry.code,
            stock_name=data.stock.name,
            dossier=dossier,
            metric_text=metric_text,
            settings=settings,
            as_of=as_of,
        )
        store_tier2(connection, context.run_id, entry.code, outcome)
        context.add_usage(outcome.usage.total_tokens, outcome.usage.cost)
        if outcome.score is not None:
            scores[entry.code] = outcome.score
    return scores


def _finalize(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
    universe: UniverseData,
    settings: Settings,
    as_of: date,
    fundamentals: dict[str, FundamentalResult],
    momentum: dict[str, MomentumResult],
    tier2_scores: dict[str, Tier2Score],
    veto_events: dict[str, list[VetoEvent]],
) -> dict[str, CompositeResult]:
    results: dict[str, CompositeResult] = {}
    for code in veto_events:
        results[code] = compose_score(
            0.0,
            0.0,
            None,
            settings,
            hard_veto=True,
        )
    for code, fund in fundamentals.items():
        mom = momentum.get(code)
        if mom is None:
            continue
        outlook = tier2_scores[code].score if code in tier2_scores else None
        risk_tags = tier2_scores[code].risk_tags if code in tier2_scores else []
        critical = any(
            tag.severity == "critical" and tag.tag in ("疑似炒作", "叙事背离") for tag in risk_tags
        )
        data = universe.data.get(code)
        soft_events = (
            check_soft_downgrade(
                data,
                settings,
                as_of,
                llm_critical_risk=critical,
            )
            if data is not None
            else []
        )
        results[code] = compose_score(
            fund.total,
            mom.score,
            outlook,
            settings,
            soft_events=soft_events,
        )
    store_final_scores(connection, run_id, results)
    return results


def _audit_counts(
    pool: Sequence[PoolEntry],
    tier2_scores: dict[str, Tier2Score],
) -> tuple[int, int]:
    ok = sum(1 for entry in pool if entry.code in tier2_scores)
    return ok, len(pool) - ok


def run_weekly(
    connection: duckdb.DuckDBPyConnection,
    settings: Settings,
    *,
    until: str = "S8",
    as_of: date | None = None,
    codes: Sequence[str] | None = None,
    refresh: bool = False,
    resume: bool | str | None = False,
    client: LlmCompleter | None = None,
    use_lock: bool = True,
    push: bool = True,
    now: datetime | None = None,
) -> WeeklyResult:
    """执行周日流水线。

    ``resume`` 为 ``True`` 时续跑最近一次未成功的运行；传入运行编号时
    只续跑该运行，编号不存在或已成功会抛出 :class:`ValueError`。
    """
    target = _parse_until(until)
    resume_run_id = resume if isinstance(resume, str) else None
    if resume_run_id in {"", "latest"}:
        resume_run_id = None
    lock = FileLock(PIPELINE) if use_lock else _NullLock()
    with lock:
        if resume:
            context = _restore_context(connection, resume_run_id)
            stored_as_of, stored_codes = _read_state(context.run_id)
            run_date = stored_as_of or context.started_at.date()
            codes = list(codes) if codes is not None else stored_codes
            completed = {step for step, status in context.step_status.items() if status == "done"}
        else:
            run_date = as_of or date.today()
            context = RunContext.start(PIPELINE, now=now)
            completed = set()
            _write_state(context.run_id, as_of=run_date, codes=codes)
        context.save(connection)
        log.info(
            "pipeline.weekly.start",
            run_id=context.run_id,
            until=target,
            resume=resume,
        )

        filter_results: dict[str, FilterResult] = {}
        veto_events: dict[str, list[VetoEvent]] = {}
        fundamentals: dict[str, FundamentalResult] = {}
        momentum: dict[str, MomentumResult] = {}
        data_flags: dict[str, str | None] = {}
        pool: list[PoolEntry] = []
        dossiers: dict[str, Tier1Dossier] = {}
        tier2_scores: dict[str, Tier2Score] = {}
        final_scores: dict[str, CompositeResult] = {}
        quant_check_path: Path | None = None
        report_path: Path | None = None
        chart_path: Path | None = None
        llm_skipped = False
        llm_skip_reason: str | None = None

        try:
            if _reached("S1", target) and "S1" not in completed:

                def step_refresh() -> None:
                    if not refresh:
                        return
                    summary = run_ingest(
                        connection,
                        settings,
                        codes=list(codes) if codes is not None else None,
                        backfill_text=False,
                    )
                    if summary.warnings.get("announcement_text"):
                        context.warn_step("S1_data", summary.warnings["announcement_text"])
                    if summary.errors:
                        failed = "；".join(
                            f"{key}: {value}" for key, value in summary.errors.items()
                        )
                        raise RuntimeError(f"数据刷新失败：{failed}")

                _run_step(context, connection, "S1", step_refresh)

            universe = load_universe(connection, as_of=run_date, codes=codes)
            if _reached("S2", target):
                if "S2" in completed:
                    filter_results = _load_filter_results(connection, context.run_id)
                    veto_events = _load_veto_events(connection, context.run_id)
                else:
                    filter_results, veto_events = _run_step(
                        context,
                        connection,
                        "S2",
                        lambda: _stage0(universe, settings, run_date),
                    )
                    store_filter_results(connection, context.run_id, filter_results.values())
                    store_veto_events(connection, context.run_id, veto_events)

            if _reached("S3", target):
                if "S3" in completed:
                    fundamentals, momentum, data_flags = load_quant_state(
                        connection, context.run_id
                    )
                else:
                    candidates = [
                        universe.data[code]
                        for code, result in filter_results.items()
                        if result.passed
                    ]
                    peer_universe = (
                        load_universe(connection, as_of=run_date) if codes is not None else universe
                    )
                    fundamentals, momentum, data_flags = _run_step(
                        context,
                        connection,
                        "S3",
                        lambda: _score(
                            connection,
                            context.run_id,
                            candidates,
                            settings,
                            run_date,
                            [
                                data
                                for data in peer_universe.data.values()
                                if not data.stock.is_st
                                and data.stock.list_date is not None
                                and (run_date - data.stock.list_date).days >= 365
                            ],
                        ),
                    )

            if _reached("S4", target):
                if "S4" in completed:
                    pool = _load_pool(connection, context.run_id)
                else:
                    pool = _run_step(
                        context,
                        connection,
                        "S4",
                        lambda: _llm_pool(
                            connection,
                            context.run_id,
                            universe,
                            settings,
                            run_date,
                            filter_results,
                            veto_events,
                            fundamentals,
                            momentum,
                            data_flags,
                        ),
                    )
                if not (paths.reports_dir() / "quant_check.md").exists() or "S4" not in completed:
                    rows = _quant_check_rows(
                        universe,
                        filter_results,
                        fundamentals,
                        momentum,
                        data_flags,
                        pool,
                    )
                    quant_check_path = write_quant_check(
                        run_id=context.run_id,
                        as_of=run_date,
                        rows=rows,
                        universe_count=len(universe.stocks),
                        stage0_passed=sum(1 for result in filter_results.values() if result.passed),
                        hard_veto=len(veto_events),
                        pool_count=len(pool),
                    )
                else:
                    quant_check_path = paths.reports_dir() / "quant_check.md"

            need_llm = (_reached("S5", target) and "S5" not in completed) or (
                _reached("S6", target) and "S6" not in completed
            )
            llm: LlmCompleter | None = None
            skipped_steps: set[str] = set()
            if need_llm:
                try:
                    llm = _ensure_client(client, settings)
                except LlmNotConfiguredError as exc:
                    llm_skipped = True
                    llm_skip_reason = str(exc)
                    for step in ("S5", "S6"):
                        if _reached(step, target) and step not in completed:
                            skipped_steps.add(step)
                            context.step_status[step] = f"skipped:{llm_skip_reason}"
                    context.save(connection)
                    log.warning(
                        "pipeline.weekly.llm_skipped",
                        run_id=context.run_id,
                        reason=llm_skip_reason,
                    )

            # Refresh candidate materials after selection, before assembling Tier-1.
            if llm is not None and _reached("S5", target) and "S5" not in completed:
                try:
                    material_result = backfill_announcement_text(
                        connection,
                        DataClient(settings),
                        codes=[item.code for item in pool],
                        limit=100 if refresh else 0,
                        as_of=run_date,
                        lookback_days=settings.llm.material_lookback_days,
                    )
                    stats = (
                        f"required={material_result.required}, "
                        f"completed={material_result.completed}, "
                        f"failed={len(material_result.failed)}, deferred={material_result.deferred}"
                    )
                    if material_result.failed or material_result.deferred:
                        context.warn_step("S5_materials", stats)
                    else:
                        context.step_status["S5_materials"] = f"done: {stats}"
                    universe = load_universe(connection, as_of=run_date, codes=codes)
                except Exception as exc:
                    context.warn_step("S5_materials", f"候选公告正文补全失败: {exc}")
                    log.warning("pipeline.weekly.materials_failed", error=str(exc))

            if _reached("S5", target):
                if "S5" in completed:
                    dossiers = _load_tier1_dossiers(connection, context.run_id)
                elif "S5" not in skipped_steps:
                    dossiers = _run_step(
                        context,
                        connection,
                        "S5",
                        lambda: _tier1_step(
                            connection,
                            context,
                            universe,
                            settings,
                            run_date,
                            pool,
                            llm,  # type: ignore[arg-type]
                        ),
                    )

            if _reached("S6", target):
                if "S6" in completed:
                    tier2_scores = _load_tier2_scores(connection, context.run_id)
                elif "S6" not in skipped_steps:
                    tier2_scores = _run_step(
                        context,
                        connection,
                        "S6",
                        lambda: _tier2_step(
                            connection,
                            context,
                            universe,
                            settings,
                            run_date,
                            pool,
                            dossiers,
                            fundamentals,
                            momentum,
                            llm,  # type: ignore[arg-type]
                        ),
                    )

            if _reached("S7", target):
                if "S7" in completed:
                    final_scores = _load_final_scores(connection, context.run_id)
                else:
                    final_scores = _run_step(
                        context,
                        connection,
                        "S7",
                        lambda: _finalize(
                            connection,
                            context.run_id,
                            universe,
                            settings,
                            run_date,
                            fundamentals,
                            momentum,
                            tier2_scores,
                            veto_events,
                        ),
                    )

            if _reached("S8", target):
                if "S8" in completed:
                    report_path = paths.reports_dir() / f"{context.run_id}.md"
                    chart_file = paths.reports_dir() / f"{context.run_id}.png"
                    chart_path = chart_file if chart_file.is_file() else None
                else:
                    context.finish()
                    context.save(connection)
                    report = cast(
                        WeeklyReport,
                        _run_step(
                            context,
                            connection,
                            "S8",
                            lambda: build_weekly_report(
                                connection,
                                context.run_id,
                                as_of=run_date,
                                push=push,
                            ),
                        ),
                    )
                    report_path = report.path
                    chart_path = report.chart_path
        except KeyboardInterrupt:
            context.fail("用户中断")
            context.save(connection)
            raise
        except Exception as exc:
            context.fail(str(exc))
            context.save(connection)
            log.error("pipeline.weekly.failed", run_id=context.run_id, error=str(exc))
            raise

        context.finish()
        context.save(connection)
        audit_ok, audit_failed = (0, 0) if llm_skipped else _audit_counts(pool, tier2_scores)
        log.info(
            "pipeline.weekly.done",
            run_id=context.run_id,
            stage0_passed=sum(1 for result in filter_results.values() if result.passed),
            pool=len(pool),
            audit_failed=audit_failed,
        )
        return WeeklyResult(
            run_id=context.run_id,
            as_of=run_date,
            universe_count=len(universe.stocks),
            stage0_passed_count=sum(1 for result in filter_results.values() if result.passed),
            hard_veto_count=len(veto_events),
            filter_results=filter_results,
            veto_events=veto_events,
            fundamentals=fundamentals,
            momentum=momentum,
            data_flags=data_flags,
            pool=pool,
            quant_check_path=quant_check_path,
            final_scores=final_scores,
            audit_ok_count=audit_ok,
            audit_failed_count=audit_failed,
            report_path=report_path,
            chart_path=chart_path,
            llm_skipped=llm_skipped,
            llm_skip_reason=llm_skip_reason,
        )


class _NullLock:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> None:
        del args
