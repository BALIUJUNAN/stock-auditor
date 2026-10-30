from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from stock_auditor.config import Settings, load_settings
from stock_auditor.db import apply_migrations
from stock_auditor.domain import (
    AnnouncementRow,
    QuoteBar,
    ResearchRow,
    StockData,
    StockInfo,
    ValuationRow,
)
from stock_auditor.funnel import (
    ANNOUNCEMENT,
    FOCUS_VALUE,
    QUANT,
    RESEARCH,
    WATCHLIST,
    PoolCandidate,
    PoolEntry,
    WatchlistError,
    build_llm_pool,
    load_watchlist,
    store_llm_pool,
)

AS_OF = date(2026, 10, 29)


def _settings(**funnel: object) -> Settings:
    base = load_settings()
    return base.model_copy(
        update={"funnel": base.funnel.model_copy(update=funnel)}
    )


def _quotes(last_close: float) -> tuple[QuoteBar, ...]:
    bars = [
        QuoteBar(
            trade_date=AS_OF - timedelta(days=20 - index),
            open=10.0,
            high=10.0,
            low=10.0,
            close=10.0,
            volume=1_000_000.0,
            amount=10_000_000.0,
            turnover=0.05,
        )
        for index in range(20)
    ]
    bars.append(
        QuoteBar(
            trade_date=AS_OF,
            open=10.0,
            high=10.0,
            low=10.0,
            close=last_close,
            volume=1_000_000.0,
            amount=10_000_000.0,
            turnover=0.05,
        )
    )
    return tuple(bars)


def _candidate(
    code: str,
    fundamental: float,
    momentum: float,
    *,
    stage0_passed: bool = True,
    hard_veto: bool = False,
    data_flag: str | None = None,
    sw_l1: str = "电子",
    pe: float | None = 20.0,
    quotes: tuple[QuoteBar, ...] = (),
    announcements: tuple[AnnouncementRow, ...] = (),
    research: tuple[ResearchRow, ...] = (),
) -> PoolCandidate:
    valuations = (
        (ValuationRow(trade_date=AS_OF, pe_ttm=pe),) if pe is not None else ()
    )
    data = StockData(
        stock=StockInfo(
            code=code,
            name=code,
            board="sh_main",
            list_date=None,
            sw_l1=sw_l1,
            sw_l2=None,
        ),
        quotes=quotes,
        valuations=valuations,
        announcements=announcements,
        research=research,
    )
    return PoolCandidate(
        data=data,
        fundamental=fundamental,
        momentum=momentum,
        stage0_passed=stage0_passed,
        hard_veto=hard_veto,
        data_flag=data_flag,
    )


def _entries(entries: list[PoolEntry]) -> list[tuple[str, str]]:
    return [(entry.code, entry.source) for entry in entries]


def test_quant_pool_sorts_by_total_then_fundamental() -> None:
    candidates = [
        _candidate("000001", 30.0, 20.0),
        _candidate("000002", 35.0, 10.0),
        _candidate("000003", 25.0, 20.0),
        _candidate("000004", 30.0, 15.0),
    ]
    result = build_llm_pool(candidates, _settings(quant_top_n=2), as_of=AS_OF)
    assert _entries(result) == [("000001", QUANT), ("000002", QUANT)]


def test_quant_pool_excludes_failed_vetoed_and_suspect() -> None:
    candidates = [
        _candidate("000001", 10.0, 5.0),
        _candidate("000002", 39.0, 20.0, stage0_passed=False),
        _candidate("000003", 39.0, 19.0, hard_veto=True),
        _candidate("000004", 39.0, 18.0, data_flag="数据存疑"),
    ]
    result = build_llm_pool(candidates, _settings(), as_of=AS_OF)
    assert _entries(result) == [("000001", QUANT)]


def test_watchlist_is_added_even_without_stage0() -> None:
    candidates = [
        _candidate("000001", 10.0, 5.0),
        _candidate("000002", 5.0, 0.0, stage0_passed=False),
        _candidate("000003", 5.0, 0.0, hard_veto=True),
    ]
    result = build_llm_pool(
        candidates,
        _settings(quant_top_n=1),
        as_of=AS_OF,
        watchlist_codes=["000001", "000002", "000003", "999999"],
    )
    assert _entries(result) == [
        ("000001", QUANT),
        ("000002", WATCHLIST),
    ]


def test_focus_value_requires_focus_industry_and_below_median_pe() -> None:
    candidates = [
        _candidate("000001", 30.0, 5.0, pe=10.0),
        _candidate("000002", 20.0, 5.0, pe=12.0),
        _candidate("000003", 25.0, 5.0, pe=100.0),
        _candidate("000004", 39.0, 5.0, pe=5.0, sw_l1="银行"),
        _candidate("000005", 19.0, 5.0, pe=5.0, sw_l1="医药生物"),
        _candidate("000006", 35.0, 5.0, pe=-5.0),
        _candidate("000007", 35.0, 5.0, stage0_passed=False, pe=50.0),
        _candidate("000008", 1.0, 5.0, pe=50.0, sw_l1="医药生物"),
        _candidate("000009", 0.0, 5.0, pe=100.0),
    ]
    result = build_llm_pool(
        candidates, _settings(quant_top_n=0), as_of=AS_OF
    )
    assert _entries(result) == [
        ("000001", FOCUS_VALUE),
        ("000002", FOCUS_VALUE),
        ("000005", FOCUS_VALUE),
    ]


def test_focus_value_takes_top_n_by_fundamental() -> None:
    base = load_settings()
    settings = _settings(quant_top_n=0)
    settings = settings.model_copy(
        update={
            "funnel": settings.funnel.model_copy(
                update={
                    "supplement": base.funnel.supplement.model_copy(
                        update={"focus_value": 2}
                    )
                }
            )
        }
    )
    candidates = [
        _candidate("000001", 10.0, 0.0, pe=15.0),
        _candidate("000002", 30.0, 0.0, pe=5.0),
        _candidate("000003", 20.0, 0.0, pe=10.0),
        _candidate("000004", 5.0, 0.0, pe=100.0),
    ]
    result = build_llm_pool(candidates, settings, as_of=AS_OF)
    assert [entry.code for entry in result] == ["000002", "000003"]


def test_announcement_supplement_uses_keywords_and_lookback() -> None:
    def ann(days_ago: int, title: str) -> AnnouncementRow:
        return AnnouncementRow(ann_date=AS_OF - timedelta(days=days_ago), title=title)

    candidates = [
        _candidate("000001", 10.0, 0.0, announcements=(ann(1, "关于重大合同的公告"),)),
        _candidate("000002", 20.0, 0.0, announcements=(ann(3, "新药获批公告"),)),
        _candidate("000003", 30.0, 0.0, announcements=(ann(15, "重大合同公告"),)),
        _candidate("000004", 40.0, 0.0, announcements=(ann(2, "董事会决议公告"),)),
    ]
    result = build_llm_pool(candidates, _settings(quant_top_n=0), as_of=AS_OF)
    assert _entries(result) == [
        ("000001", ANNOUNCEMENT),
        ("000002", ANNOUNCEMENT),
    ]


def test_announcement_supplement_caps_at_five_latest() -> None:
    candidates = [
        _candidate(
            f"00000{index}",
            float(index),
            0.0,
            announcements=(
                AnnouncementRow(
                    ann_date=AS_OF - timedelta(days=index),
                    title="重大合同公告",
                ),
            ),
        )
        for index in range(1, 8)
    ]
    result = build_llm_pool(candidates, _settings(quant_top_n=0), as_of=AS_OF)
    assert [entry.code for entry in result] == [
        "000001",
        "000002",
        "000003",
        "000004",
        "000005",
    ]


def test_research_supplement_requires_visits_and_flat_price() -> None:
    def visits(days: list[int], *, orgs: int = 1) -> tuple[ResearchRow, ...]:
        return tuple(
            ResearchRow(visit_date=AS_OF - timedelta(days=day), org=f"org{org}")
            for day in days
            for org in range(orgs)
        )

    candidates = [
        _candidate(
            "000001",
            10.0,
            0.0,
            quotes=_quotes(10.2),
            research=visits([2, 3, 4], orgs=2),
        ),
        _candidate(
            "000002",
            20.0,
            0.0,
            quotes=_quotes(10.2),
            research=visits([2, 2, 3], orgs=2),
        ),
        _candidate(
            "000003",
            30.0,
            0.0,
            quotes=_quotes(10.6),
            research=visits([2, 3, 4]),
        ),
        _candidate(
            "000004",
            40.0,
            0.0,
            quotes=_quotes(10.2),
            research=visits([31, 32, 33]),
        ),
        _candidate("000005", 50.0, 0.0, quotes=_quotes(10.2)),
    ]
    result = build_llm_pool(candidates, _settings(quant_top_n=0), as_of=AS_OF)
    assert _entries(result) == [("000001", RESEARCH)]


def test_supplement_sources_dedupe_and_first_source_wins() -> None:
    announcements = (
        AnnouncementRow(
            ann_date=AS_OF - timedelta(days=1), title="重大合同公告"
        ),
    )
    candidates = [
        _candidate(
            "000001",
            20.0,
            0.0,
            announcements=announcements,
            pe=5.0,
            quotes=_quotes(10.2),
        )
    ]
    result = build_llm_pool(
        candidates,
        _settings(quant_top_n=0),
        as_of=AS_OF,
        watchlist_codes=["000001"],
    )
    assert _entries(result) == [("000001", WATCHLIST)]


def test_pool_total_is_capped() -> None:
    candidates = [_candidate(f"{index:06d}", 10.0, 0.0) for index in range(50)]
    extra_codes = [f"9{index:05d}" for index in range(30)]
    candidates += [
        _candidate(code, 1.0, 0.0, stage0_passed=False) for code in extra_codes
    ]
    result = build_llm_pool(
        candidates,
        _settings(),
        as_of=AS_OF,
        watchlist_codes=extra_codes,
    )
    assert len(result) == 75
    assert [entry.source for entry in result].count(QUANT) == 50
    assert [entry.source for entry in result].count(WATCHLIST) == 25


def test_watchlist_loader_reads_and_dedupes(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text(
        "\n".join(
            [
                "holdings:",
                "  - {code: '002773', name: 康弘药业, note: 长期持有}",
                "  - {code: '002185'}",
                "watchlist:",
                "  - {code: 2185}",
                "  - {code: '002724', name: 海洋王}",
            ]
        ),
        encoding="utf-8",
    )
    result = load_watchlist(path, max_entries=20)
    assert result.codes == ("002773", "002185", "002724")
    assert result.holdings[0].name == "康弘药业"
    assert result.holdings[0].note == "长期持有"


def test_watchlist_loader_missing_file_is_empty(tmp_path: Path) -> None:
    result = load_watchlist(tmp_path / "absent.yaml")
    assert result.codes == ()


def test_watchlist_loader_rejects_bad_code(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text("holdings:\n  - {code: '12345'}\n", encoding="utf-8")
    with pytest.raises(WatchlistError):
        load_watchlist(path)


def test_watchlist_loader_enforces_max_entries(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text(
        "holdings:\n  - {code: '000001'}\n  - {code: '000002'}\n",
        encoding="utf-8",
    )
    with pytest.raises(WatchlistError):
        load_watchlist(path, max_entries=1)


def test_watchlist_entries_are_written_to_database(tmp_path: Path) -> None:
    with duckdb.connect(str(tmp_path / "test.duckdb")) as connection:
        apply_migrations(connection)
        count = store_llm_pool(
            connection,
            "weekly-20261029-200000",
            [
                PoolEntry(code="002773", source=QUANT),
                PoolEntry(code="002185", source=WATCHLIST),
            ],
        )
        assert count == 2
        rows = connection.execute(
            "SELECT code, source FROM llm_pool ORDER BY code"
        ).fetchall()
        assert rows == [("002185", WATCHLIST), ("002773", QUANT)]
