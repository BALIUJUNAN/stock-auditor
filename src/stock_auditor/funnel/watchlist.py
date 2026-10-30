"""关注名单：``config/local/watchlist.yaml`` 的加载与校验。

文件分为 ``holdings``（持仓）与 ``watchlist``（重点关注）两组，
两组合计去重后不得超过 ``funnel.watchlist_max``。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from stock_auditor import paths


class WatchlistError(ValueError):
    """关注名单文件格式错误。"""


@dataclass(frozen=True)
class WatchEntry:
    code: str
    name: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class Watchlist:
    holdings: tuple[WatchEntry, ...] = ()
    watchlist: tuple[WatchEntry, ...] = ()

    @property
    def codes(self) -> tuple[str, ...]:
        """持仓在前、重点关注在后，已去重。"""
        seen: set[str] = set()
        ordered: list[str] = []
        for entry in (*self.holdings, *self.watchlist):
            if entry.code not in seen:
                seen.add(entry.code)
                ordered.append(entry.code)
        return tuple(ordered)


def default_watchlist_path() -> Path:
    return paths.local_config_dir() / "watchlist.yaml"


def _normalize_code(value: object) -> str:
    if isinstance(value, bool) or value is None:
        raise WatchlistError(f"股票代码格式错误：{value!r}")
    text = str(value).zfill(6) if isinstance(value, int) else str(value).strip()
    if len(text) != 6 or not text.isdigit():
        raise WatchlistError(f"股票代码必须是 6 位数字：{value!r}")
    return text


def _parse_entries(raw: object, section: str) -> tuple[WatchEntry, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise WatchlistError(f"watchlist.{section} 必须是列表")
    entries: list[WatchEntry] = []
    for item in raw:
        if not isinstance(item, dict) or "code" not in item:
            raise WatchlistError(f"watchlist.{section} 的每一项必须是包含 code 的映射")
        name = item.get("name")
        note = item.get("note")
        if name is not None and not isinstance(name, str):
            raise WatchlistError(f"watchlist.{section}.name 必须是字符串")
        if note is not None and not isinstance(note, str):
            raise WatchlistError(f"watchlist.{section}.note 必须是字符串")
        entries.append(
            WatchEntry(
                code=_normalize_code(item["code"]),
                name=name,
                note=note,
            )
        )
    return tuple(entries)


def _entry_payload(entry: WatchEntry) -> dict[str, str]:
    payload: dict[str, str] = {"code": entry.code}
    if entry.name:
        payload["name"] = entry.name
    if entry.note:
        payload["note"] = entry.note
    return payload


def add_watch_entry(
    code: str,
    *,
    name: str | None = None,
    note: str | None = None,
    path: Path | None = None,
    max_entries: int | None = None,
) -> bool:
    """把代码加入 ``watchlist`` 组；已在名单中返回 ``False``。

    文件不存在时创建；超过 ``max_entries`` 时抛出 :class:`WatchlistError`。
    写回会重排 YAML（注释不保留），并采用临时文件替换避免半截文件。
    """
    target = Path(path) if path is not None else default_watchlist_path()
    normalized = _normalize_code(code)
    current = load_watchlist(target)
    if normalized in current.codes:
        return False
    if max_entries is not None and len(current.codes) + 1 > max_entries:
        raise WatchlistError(
            f"关注名单已满：最多 {max_entries} 只，请先在 watchlist.yaml 中删除"
        )

    if target.exists():
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise WatchlistError("关注名单顶层必须是映射")
        data = dict(raw)
    else:
        data = {}

    entries = data.get("watchlist")
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise WatchlistError("watchlist.watchlist 必须是列表")

    new_entry = WatchEntry(code=normalized, name=name, note=note)
    data["watchlist"] = [*entries, _entry_payload(new_entry)]
    data.setdefault("holdings", [])

    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)
    return True


def load_watchlist(
    path: Path | None = None,
    *,
    max_entries: int | None = None,
) -> Watchlist:
    """读取关注名单；文件不存在时返回空名单。

    ``max_entries`` 通常传 ``settings.funnel.watchlist_max``，
    去重后的代码总数超限时抛出 :class:`WatchlistError`。
    """
    target = Path(path) if path is not None else default_watchlist_path()
    if not target.exists():
        return Watchlist()

    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - 具体错误信息因版本而异
        raise WatchlistError(f"关注名单 YAML 解析失败：{exc}") from exc

    if raw is None:
        return Watchlist()
    if not isinstance(raw, dict):
        raise WatchlistError("关注名单顶层必须是映射")

    watchlist = Watchlist(
        holdings=_parse_entries(raw.get("holdings"), "holdings"),
        watchlist=_parse_entries(raw.get("watchlist"), "watchlist"),
    )
    if max_entries is not None and len(watchlist.codes) > max_entries:
        raise WatchlistError(
            f"关注名单共 {len(watchlist.codes)} 只，超过上限 {max_entries} 只"
        )
    return watchlist
