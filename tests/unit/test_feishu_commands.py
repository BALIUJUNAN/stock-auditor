"""T3.3：飞书指令、授权、限流与按钮回调。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from stock_auditor.config import load_settings
from stock_auditor.db import apply_migrations
from stock_auditor.feishu import (
    ALERT_BUTTONS,
    BUTTON_IGNORE,
    BUTTON_WATCH,
    CommandService,
    FeishuConfig,
    is_ignored,
)
from stock_auditor.funnel import load_watchlist
from stock_auditor.report import build_alert_card

AS_OF = date(2026, 10, 29)
NOW = datetime(2026, 10, 29, 20, 0, 0)
RUN_ID = "weekly-20261029-200000"
CHAT_ID = "chat-1"
USER_ID = "user-1"

CONFIG = FeishuConfig(
    channel="app",
    chat_id=CHAT_ID,
    allowed_chat_ids=[CHAT_ID],
    allowed_user_ids=[USER_ID],
)


def _insert_stock(
    connection: duckdb.DuckDBPyConnection,
    code: str,
    name: str,
) -> None:
    connection.execute(
        "INSERT INTO stock_universe (code, name, board, list_date, sw_l1, sw_l2) "
        "VALUES (?, ?, 'sz_main', DATE '2000-01-01', '电子', '半导体')",
        [code, name],
    )
    connection.executemany(
        "INSERT INTO daily_quotes (code, trade_date, open, high, low, close, "
        "volume, amount, turnover) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                code,
                AS_OF - timedelta(days=79 - index),
                10.0,
                10.0,
                9.7,
                10.0,
                1_000_000.0,
                100_000_000.0,
                0.05,
            )
            for index in range(80)
        ],
    )


def _seed(connection: duckdb.DuckDBPyConnection) -> None:
    _insert_stock(connection, "000001", "测试甲")
    _insert_stock(connection, "000002", "测试乙")
    connection.execute(
        "INSERT INTO run_log (run_id, pipeline, started_at, finished_at, status, "
        "step_status, llm_tokens, llm_cost, error) "
        "VALUES (?, 'weekly', ?, ?, 'success', '{}', 120, 0.5, NULL)",
        [RUN_ID, NOW, NOW],
    )
    connection.executemany(
        "INSERT INTO quant_scores (run_id, code, raw_values, industry_percentiles, "
        "scores, is_imputed, fundamental, momentum, tags, data_flag) "
        "VALUES (?, ?, '{}', '{}', '{}', '{}', ?, ?, '[]', '未交叉验证')",
        [(RUN_ID, "000001", 35.0, 15.0), (RUN_ID, "000002", 20.0, 10.0)],
    )


@pytest.fixture()
def connection(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    db = duckdb.connect(str(tmp_path / "commands.duckdb"))
    apply_migrations(db)
    _seed(db)
    try:
        yield db
    finally:
        db.close()


def _service(
    connection: duckdb.DuckDBPyConnection,
    tmp_path: Path,
    *,
    clock=lambda: NOW,
    config: FeishuConfig | None = CONFIG,
) -> CommandService:
    return CommandService(
        settings=load_settings(),
        config=config,
        connection=connection,
        clock=clock,
        watchlist_path=tmp_path / "watchlist.yaml",
        ignored_path=tmp_path / "ignored.json",
    )


def _content(card: dict[str, Any]) -> str:
    return card["body"]["elements"][0]["content"]


def test_unauthorized_chat_or_user_is_ignored(
    connection: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    service = _service(connection, tmp_path)
    assert (
        service.handle_text("/状态", chat_id="other-chat", user_id=USER_ID) is None
    )
    assert (
        service.handle_text("/状态", chat_id=CHAT_ID, user_id="other-user") is None
    )
    assert (
        service.handle_text("/状态", chat_id=CHAT_ID, user_id=USER_ID) is not None
    )

    disabled = FeishuConfig(channel="app", chat_id=CHAT_ID)
    service = _service(connection, tmp_path, config=disabled)
    assert service.handle_text("/状态", chat_id=CHAT_ID, user_id=USER_ID) is None


def test_non_command_and_unknown_command(
    connection: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    service = _service(connection, tmp_path)
    assert service.handle_text("今天怎么样", chat_id=CHAT_ID, user_id=USER_ID) is None

    help_card = service.handle_text("/帮助", chat_id=CHAT_ID, user_id=USER_ID)
    assert help_card is not None
    assert "/查 000001" in _content(help_card)

    unknown = service.handle_text("/foo", chat_id=CHAT_ID, user_id=USER_ID)
    assert unknown is not None
    assert "未知指令" in unknown["header"]["title"]["content"]


def test_query_returns_card_and_enforces_rate_limit(
    connection: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    now = [NOW]
    service = _service(connection, tmp_path, clock=lambda: now[0])

    bad = service.handle_text("/查 abc", chat_id=CHAT_ID, user_id=USER_ID)
    assert bad is not None
    assert "代码格式错误" in bad["header"]["title"]["content"]

    card = service.handle_text("/查 000001", chat_id=CHAT_ID, user_id=USER_ID)
    assert card is not None
    assert "测试甲 000001" in card["header"]["title"]["content"]
    text = _content(card)
    assert "基本面 35/40" in text
    assert "动量 15/20" in text
    assert "合计 50/100" in text
    assert "未执行 LLM 审计" in text
    assert "未交叉验证" in text

    limited = service.handle_text("/查 000002", chat_id=CHAT_ID, user_id=USER_ID)
    assert limited is not None
    assert "操作过于频繁" in limited["header"]["title"]["content"]

    now[0] = NOW + timedelta(minutes=11)
    second = service.handle_text("/查 000002", chat_id=CHAT_ID, user_id=USER_ID)
    assert second is not None
    assert "测试乙 000002" in second["header"]["title"]["content"]

    now[0] = NOW + timedelta(minutes=22)
    missing = service.handle_text("/查 600519", chat_id=CHAT_ID, user_id=USER_ID)
    assert missing is not None
    assert "未找到股票" in missing["header"]["title"]["content"]


def test_weekly_command_uses_latest_report(
    connection: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    service = _service(connection, tmp_path)
    empty = service.handle_text("/周报", chat_id=CHAT_ID, user_id=USER_ID)
    assert empty is not None
    assert "暂无周报" in _content(empty)

    payload = {
        "run_id": RUN_ID,
        "as_of": AS_OF.isoformat(),
        "status": "success",
        "counts": {"llm_tokens": 120, "llm_cost": 0.5},
        "main_markdown": "1. **测试甲（000001）** ★★★★ 80 分",
        "footer": "完整周报：var/reports/weekly.md",
        "report_url": "file:///var/reports/weekly.md",
    }
    connection.execute(
        "INSERT INTO weekly_reports (run_id, report_json, markdown) "
        "VALUES (?, ?, '# 周报')",
        [RUN_ID, json.dumps(payload, ensure_ascii=False)],
    )

    card = service.handle_text("/周报", chat_id=CHAT_ID, user_id=USER_ID)
    assert card is not None
    assert "2026-10-29" in card["header"]["title"]["content"]
    assert "测试甲" in _content(card)
    assert "button" not in json.dumps(card, ensure_ascii=False)


def test_status_command_reports_runs_and_counts(
    connection: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    connection.execute(
        "INSERT INTO run_log (run_id, pipeline, started_at, finished_at, status, "
        "step_status, llm_tokens, llm_cost) "
        "VALUES ('daily-20261030-163000', 'daily', ?, ?, 'success', '{}', 0, 0)",
        [datetime(2026, 10, 30, 16, 30), datetime(2026, 10, 30, 16, 31)],
    )
    service = _service(connection, tmp_path)
    card = service.handle_text("/状态", chat_id=CHAT_ID, user_id=USER_ID)
    assert card is not None
    text = _content(card)
    assert RUN_ID in text
    assert "daily-20261030-163000" in text
    assert "股票池" in text and "2 只" in text
    assert "未配置" in text


def test_buttons_watch_and_ignore(
    connection: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    service = _service(connection, tmp_path)

    watched = service.handle_action(
        BUTTON_WATCH, "000001", chat_id=CHAT_ID, user_id=USER_ID
    )
    assert watched is not None
    assert "已加入关注名单" in _content(watched)
    watchlist = load_watchlist(tmp_path / "watchlist.yaml", max_entries=20)
    assert watchlist.codes == ("000001",)
    assert watchlist.watchlist[0].name == "测试甲"

    again = service.handle_action(
        BUTTON_WATCH, "000001", chat_id=CHAT_ID, user_id=USER_ID
    )
    assert again is not None
    assert "已在关注名单" in _content(again)

    ignored = service.handle_action(
        BUTTON_IGNORE, "000001", chat_id=CHAT_ID, user_id=USER_ID
    )
    assert ignored is not None
    assert "本周将忽略" in _content(ignored)
    assert is_ignored("000001", path=tmp_path / "ignored.json", as_of=AS_OF)
    assert not is_ignored("000002", path=tmp_path / "ignored.json", as_of=AS_OF)

    ignored_again = service.handle_action(
        BUTTON_IGNORE, "000001", chat_id=CHAT_ID, user_id=USER_ID
    )
    assert ignored_again is not None
    assert "已在" in _content(ignored_again)

    unknown = service.handle_action(
        "upgrade", "000001", chat_id=CHAT_ID, user_id=USER_ID
    )
    assert unknown is not None
    assert "未知操作" in unknown["header"]["title"]["content"]

    assert (
        service.handle_action(
            BUTTON_WATCH, "000001", chat_id=CHAT_ID, user_id="other-user"
        )
        is None
    )


def test_alert_buttons_match_command_actions() -> None:
    actions = {button["action"] for button in ALERT_BUTTONS}
    assert actions == {BUTTON_WATCH, BUTTON_IGNORE}
    card = build_alert_card(
        code="000001",
        name="测试甲",
        title="异动提醒",
        detail="涨幅超过阈值",
        as_of=AS_OF.isoformat(),
        buttons=ALERT_BUTTONS,
    )
    action_element = next(
        element
        for element in card["body"]["elements"]
        if element.get("tag") == "action"
    )
    callbacks = [item["behaviors"][0]["value"] for item in action_element["actions"]]
    assert callbacks == [
        {"action": BUTTON_WATCH, "code": "000001"},
        {"action": BUTTON_IGNORE, "code": "000001"},
    ]
