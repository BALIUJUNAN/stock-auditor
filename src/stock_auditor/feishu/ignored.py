"""“本周忽略”状态：``var/state/ignored.json``，按 ISO 周键控（C1 决策）。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from stock_auditor import paths

STATE_FILENAME = "ignored.json"
KEEP_WEEKS = 12


def ignored_state_path() -> Path:
    return paths.state_dir() / STATE_FILENAME


def week_key(as_of: date | None = None) -> str:
    """返回 ``2026-W44`` 形式的 ISO 周键。"""
    target = as_of or date.today()
    iso = target.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _normalize_code(code: object) -> str:
    text = str(code).strip()
    if len(text) != 6 or not text.isdigit():
        raise ValueError(f"股票代码必须是 6 位数字：{code!r}")
    return text


def load_ignored(path: Path | None = None) -> dict[str, list[str]]:
    """读取忽略状态；文件缺失或损坏时返回空映射。"""
    target = Path(path) if path is not None else ignored_state_path()
    if not target.exists():
        return {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    state: dict[str, list[str]] = {}
    for key, value in raw.items():
        if not isinstance(value, list):
            continue
        codes = [str(item) for item in value if isinstance(item, str)]
        state[str(key)] = codes
    return state


def ignored_codes(
    *,
    path: Path | None = None,
    week: str | None = None,
    as_of: date | None = None,
) -> tuple[str, ...]:
    state = load_ignored(path)
    return tuple(state.get(week or week_key(as_of), []))


def is_ignored(
    code: str,
    *,
    path: Path | None = None,
    week: str | None = None,
    as_of: date | None = None,
) -> bool:
    return _normalize_code(code) in ignored_codes(path=path, week=week, as_of=as_of)


def ignore_code(
    code: str,
    *,
    path: Path | None = None,
    week: str | None = None,
    as_of: date | None = None,
) -> bool:
    """把代码记入本周忽略名单；已存在返回 ``False``。

    仅保留最近 ``KEEP_WEEKS`` 周，避免状态文件无限增长。
    """
    target = Path(path) if path is not None else ignored_state_path()
    normalized = _normalize_code(code)
    key = week or week_key(as_of)
    state = load_ignored(target)
    codes = state.setdefault(key, [])
    if normalized in codes:
        return False
    codes.append(normalized)

    for stale in sorted(state)[:-KEEP_WEEKS]:
        state.pop(stale, None)

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return True
