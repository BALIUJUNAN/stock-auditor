from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from stock_auditor.config import load_settings
from stock_auditor.ingest.backfill import (
    BackfillState,
    StockStep,
    _fingerprint,
    backfill_stocks,
)


def _state(path: Path, fingerprint: str = "fp") -> BackfillState:
    return BackfillState(path, fingerprint)


def _step(
    name: str,
    fetch: Any,
    calls: list[str] | None = None,
) -> StockStep:
    def counted_fetch(code: str) -> list[tuple[Any, ...]]:
        if calls is not None:
            calls.append(code)
        return fetch(code)

    return StockStep(
        name=name,
        fetch=counted_fetch,
        store=lambda rows: len(rows),
    )


def test_mark_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "backfill.json"
    state = _state(path)
    state.mark("daily_quotes", "002773")
    state.mark("daily_quotes", "002185")
    state.mark("financials", "002773")

    reloaded = _state(path)
    assert reloaded.is_done("daily_quotes", "002773")
    assert reloaded.is_done("daily_quotes", "002185")
    assert reloaded.is_done("financials", "002773")
    assert not reloaded.is_done("financials", "002185")
    assert reloaded.done_count("daily_quotes") == 2
    assert reloaded.done_count("valuation_daily") == 0


def test_fingerprint_change_resets_progress(tmp_path: Path) -> None:
    path = tmp_path / "backfill.json"
    _state(path, "old").mark("daily_quotes", "002773")

    state = _state(path, "new")
    assert not state.is_done("daily_quotes", "002773")
    assert state.done_count("daily_quotes") == 0


def test_corrupt_state_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "backfill.json"
    path.write_text("{not json", encoding="utf-8")

    state = _state(path)
    assert not state.is_done("daily_quotes", "002773")

    state.mark("daily_quotes", "002773")
    assert _state(path).is_done("daily_quotes", "002773")


def test_keyboard_interrupt_propagates_and_resume_skips_done(
    tmp_path: Path,
) -> None:
    path = tmp_path / "backfill.json"
    codes = ["000001", "000002", "000003"]
    calls: list[str] = []
    interrupted = False

    def fetch(code: str) -> list[tuple[Any, ...]]:
        nonlocal interrupted
        if code == "000002" and not interrupted:
            interrupted = True
            raise KeyboardInterrupt
        return [(code,)]

    step = _step("daily_quotes", fetch, calls)
    with pytest.raises(KeyboardInterrupt):
        backfill_stocks(codes, [step], _state(path))

    state = _state(path)
    assert state.is_done("daily_quotes", "000001")
    assert not state.is_done("daily_quotes", "000002")
    assert calls == ["000001", "000002"]

    calls.clear()
    summary = backfill_stocks(codes, [step], state)
    assert calls == ["000002", "000003"]
    assert summary.counts == {"daily_quotes": 2}
    assert summary.errors == {}


def test_failed_code_is_not_marked_and_is_retried(tmp_path: Path) -> None:
    path = tmp_path / "backfill.json"
    codes = ["000001", "000002"]
    attempts: dict[str, int] = {}

    def fetch(code: str) -> list[tuple[Any, ...]]:
        attempts[code] = attempts.get(code, 0) + 1
        if code == "000002" and attempts[code] == 1:
            raise RuntimeError("transient")
        return [(code,)]

    step = _step("financials", fetch)
    summary = backfill_stocks(codes, [step], _state(path))

    assert summary.errors == {"financials:000002": "transient"}
    assert summary.code_failures == 1
    assert summary.counts == {"financials": 1}
    assert not _state(path).is_done("financials", "000002")

    second = backfill_stocks(codes, [step], _state(path))
    assert attempts == {"000001": 1, "000002": 2}
    assert second.errors == {}
    assert second.counts == {"financials": 1}


def test_steps_run_in_order_and_only_pending_codes(tmp_path: Path) -> None:
    path = tmp_path / "backfill.json"
    state = _state(path)
    state.mark("daily_quotes", "000001")
    calls: list[tuple[str, str]] = []

    def make_fetch(name: str) -> Any:
        def fetch(code: str) -> list[tuple[Any, ...]]:
            calls.append((name, code))
            return [(code,)]

        return fetch

    steps = [
        _step("daily_quotes", make_fetch("daily_quotes")),
        _step("financials", make_fetch("financials")),
    ]
    backfill_stocks(["000001", "000002"], steps, state)

    assert calls == [
        ("daily_quotes", "000002"),
        ("financials", "000001"),
        ("financials", "000002"),
    ]


def test_fingerprint_is_stable_and_reacts_to_backfill_years() -> None:
    settings = load_settings()
    assert _fingerprint(settings) == _fingerprint(load_settings())

    changed = settings.model_copy(
        update={
            "backfill": settings.backfill.model_copy(
                update={"years": settings.backfill.years + 1}
            )
        }
    )
    assert _fingerprint(settings) != _fingerprint(changed)
