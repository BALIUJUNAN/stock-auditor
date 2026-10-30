"""LLM 池（漏斗）：量化截断池与补充池（任务书第 11 节）。

补充池按关注名单 → 重点赛道低估值 → 重大公告 → 机构调研的顺序
与截断池去重后依次加入，总数不超过 ``funnel.llm_pool_max``。
每只股票只记录首次入池的来源。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from stock_auditor.config import Settings
from stock_auditor.domain import AnnouncementRow, QuoteBar, StockData

QUANT = "quant"
WATCHLIST = "watchlist"
FOCUS_VALUE = "focus_value"
ANNOUNCEMENT = "announcement"
RESEARCH = "research"


@dataclass(frozen=True)
class PoolCandidate:
    """漏斗输入：一只股票的数据与量化评分结果。"""

    data: StockData
    fundamental: float
    momentum: float
    stage0_passed: bool
    hard_veto: bool = False
    data_flag: str | None = None

    @property
    def code(self) -> str:
        return self.data.stock.code

    @property
    def quant_total(self) -> float:
        return self.fundamental + self.momentum


@dataclass(frozen=True)
class PoolEntry:
    code: str
    source: str


def _latest_pe(candidate: PoolCandidate, as_of: date) -> float | None:
    rows = [
        row
        for row in candidate.data.valuations
        if row.trade_date <= as_of and row.pe_ttm is not None
    ]
    if not rows:
        return None
    return max(rows, key=lambda row: row.trade_date).pe_ttm


def _industry_pe_medians(
    candidates: Sequence[PoolCandidate], as_of: date
) -> dict[str, float]:
    groups: dict[str, list[float]] = {}
    for candidate in candidates:
        sw_l1 = candidate.data.stock.sw_l1
        pe = _latest_pe(candidate, as_of)
        if sw_l1 and pe is not None and pe > 0:
            groups.setdefault(sw_l1, []).append(pe)
    return {sw_l1: median(values) for sw_l1, values in groups.items()}


def _return_over_last_days(
    quotes: Iterable[QuoteBar], days: int, as_of: date
) -> float | None:
    bars = sorted(
        (bar for bar in quotes if bar.close is not None and bar.trade_date <= as_of),
        key=lambda bar: bar.trade_date,
    )
    if len(bars) <= days:
        return None
    base = bars[-days - 1].close
    last = bars[-1].close
    if not base:
        return None
    return last / base - 1


def _matching_announcements(
    announcements: Iterable[AnnouncementRow],
    keywords: Sequence[str],
    as_of: date,
    lookback_days: int,
) -> list[AnnouncementRow]:
    start = as_of - timedelta(days=lookback_days)
    return [
        row
        for row in announcements
        if row.ann_date is not None
        and start <= row.ann_date <= as_of
        and any(keyword in (row.title or "") for keyword in keywords)
    ]


def _latest_major_announcement(
    candidate: PoolCandidate, settings: Settings, as_of: date
) -> date | None:
    hits = _matching_announcements(
        candidate.data.announcements,
        settings.funnel.major_announcement_keywords,
        as_of,
        settings.funnel.announcement_lookback_days,
    )
    if not hits:
        return None
    return max(row.ann_date for row in hits if row.ann_date is not None)


def _recent_research_visits(
    candidate: PoolCandidate, settings: Settings, as_of: date
) -> int:
    start = as_of - timedelta(days=settings.funnel.research_lookback_days)
    dates = {
        row.visit_date
        for row in candidate.data.research
        if start <= row.visit_date <= as_of
    }
    return len(dates)


def build_llm_pool(
    candidates: Sequence[PoolCandidate],
    settings: Settings,
    *,
    as_of: date,
    watchlist_codes: Sequence[str] = (),
) -> list[PoolEntry]:
    """按任务书第 11 节构建 LLM 池，返回去重后的入池列表。"""
    funnel = settings.funnel
    by_code = {candidate.code: candidate for candidate in candidates}
    entries: list[PoolEntry] = []
    seen: set[str] = set()

    def add(code: str, source: str) -> bool:
        if code in seen or len(entries) >= funnel.llm_pool_max:
            return False
        seen.add(code)
        entries.append(PoolEntry(code=code, source=source))
        return True

    eligible = [
        candidate
        for candidate in candidates
        if candidate.stage0_passed
        and not candidate.hard_veto
        and candidate.data_flag != settings.data_quality.cross_validation.suspect_label
    ]
    eligible.sort(
        key=lambda candidate: (
            -candidate.quant_total,
            -candidate.fundamental,
            candidate.code,
        )
    )
    for candidate in eligible[: funnel.quant_top_n]:
        add(candidate.code, QUANT)

    for code in watchlist_codes:
        candidate = by_code.get(code)
        if candidate is not None and not candidate.hard_veto:
            add(code, WATCHLIST)

    focus = set(settings.universe.focus_sw_l1)
    pe_medians = _industry_pe_medians(candidates, as_of)
    focus_picks = []
    for candidate in candidates:
        sw_l1 = candidate.data.stock.sw_l1
        if not candidate.stage0_passed or candidate.hard_veto or sw_l1 not in focus:
            continue
        pe = _latest_pe(candidate, as_of)
        industry_median = pe_medians.get(sw_l1) if sw_l1 else None
        if pe is None or industry_median is None or pe <= 0 or pe >= industry_median:
            continue
        focus_picks.append(candidate)
    focus_picks.sort(key=lambda candidate: (-candidate.fundamental, candidate.code))
    added = 0
    for candidate in focus_picks:
        if added >= funnel.supplement.focus_value:
            break
        if add(candidate.code, FOCUS_VALUE):
            added += 1

    announcement_picks: list[tuple[date, PoolCandidate]] = []
    for candidate in candidates:
        if not candidate.stage0_passed or candidate.hard_veto:
            continue
        latest = _latest_major_announcement(candidate, settings, as_of)
        if latest is not None:
            announcement_picks.append((latest, candidate))
    announcement_picks.sort(key=lambda item: (-item[0].toordinal(), item[1].code))
    added = 0
    for _, candidate in announcement_picks:
        if added >= funnel.supplement.announcements:
            break
        if add(candidate.code, ANNOUNCEMENT):
            added += 1

    research_picks = []
    for candidate in candidates:
        if not candidate.stage0_passed or candidate.hard_veto:
            continue
        visits = _recent_research_visits(candidate, settings, as_of)
        if visits < funnel.research_min_visits:
            continue
        r20 = _return_over_last_days(candidate.data.quotes, 20, as_of)
        if r20 is None or r20 >= funnel.research_max_r20:
            continue
        research_picks.append(candidate)
    research_picks.sort(key=lambda candidate: (-candidate.fundamental, candidate.code))
    added = 0
    for candidate in research_picks:
        if added >= funnel.supplement.research_visits:
            break
        if add(candidate.code, RESEARCH):
            added += 1

    return entries
