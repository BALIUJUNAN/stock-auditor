from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from stock_auditor import paths
from stock_auditor.config import load_industry_peg, load_settings


def _base_config() -> dict[str, Any]:
    """读取项目默认配置，作为测试用的完整配置基线。"""
    with (paths.config_dir() / "settings.yaml").open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    assert isinstance(data, dict)
    return data


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)


def test_project_defaults() -> None:
    settings = load_settings()

    assert settings.universe.boards == ["sh_main", "sz_main", "chinext", "star"]
    assert settings.stage0.turnover_min == pytest.approx(0.03)
    assert settings.stage0.turnover_max == pytest.approx(0.20)
    assert settings.veto.pledge_ratio_max == pytest.approx(0.70)
    assert settings.fundamental.min_analyst_count == 3
    assert settings.fundamental.revenue_cagr_years == 3
    assert settings.fundamental.history_min_valid_days == 600
    assert settings.momentum.breakdown_lookback_days == 5
    assert settings.funnel.watchlist_max == 20
    assert settings.score.star5 == 85
    assert settings.llm.temperature == 0
    assert settings.llm.token_estimate.ascii_chars_per_token == pytest.approx(3.5)
    assert settings.commercial.enabled is False


def test_local_override(tmp_path: Path) -> None:
    _write_yaml(tmp_path / "settings.yaml", _base_config())
    _write_yaml(
        tmp_path / "local" / "settings.local.yaml",
        {"universe": {"boards": ["sz_main", "chinext"]}, "score": {"star4": 70}},
    )

    settings = load_settings(tmp_path)

    assert settings.universe.boards == ["sz_main", "chinext"]
    assert settings.score.star4 == 70
    # 未被本地覆盖的键沿用默认配置
    assert settings.score.star5 == 85
    assert settings.universe.min_listing_days == 365


def test_env_overrides_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_yaml(tmp_path / "settings.yaml", _base_config())
    monkeypatch.setenv("SA__STAGE0__TURNOVER_MIN", "0.08")
    monkeypatch.setenv("SA__SCORE__STAR4", "72")

    settings = load_settings(tmp_path)

    assert settings.stage0.turnover_min == pytest.approx(0.08)
    assert settings.score.star4 == 72


def test_env_overrides_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_yaml(tmp_path / "settings.yaml", _base_config())
    monkeypatch.setenv("SA__UNIVERSE__BOARDS", '["star"]')

    settings = load_settings(tmp_path)

    assert settings.universe.boards == ["star"]


def test_unknown_key_rejected(tmp_path: Path) -> None:
    data = _base_config()
    data["stage0"]["turnover_minn"] = 0.05
    _write_yaml(tmp_path / "settings.yaml", data)

    with pytest.raises(ValidationError):
        load_settings(tmp_path)


def test_missing_key_rejected(tmp_path: Path) -> None:
    data = _base_config()
    del data["stage0"]["turnover_min"]
    _write_yaml(tmp_path / "settings.yaml", data)

    with pytest.raises(ValidationError):
        load_settings(tmp_path)


def test_invalid_range_rejected(tmp_path: Path) -> None:
    data = _base_config()
    data["stage0"]["turnover_min"] = 1.5
    _write_yaml(tmp_path / "settings.yaml", data)

    with pytest.raises(ValidationError):
        load_settings(tmp_path)


def test_turnover_bounds_rejected(tmp_path: Path) -> None:
    data = _base_config()
    data["stage0"]["turnover_min"] = 0.30
    data["stage0"]["turnover_max"] = 0.20
    _write_yaml(tmp_path / "settings.yaml", data)

    with pytest.raises(ValidationError):
        load_settings(tmp_path)


def test_missing_settings_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path)


def test_industry_peg_rules() -> None:
    rules = load_industry_peg()

    assert [rule.name for rule in rules] == ["创新药", "半导体", "云计算", "食品"]
    assert rules[0].peg_cap == pytest.approx(2.5)
    assert rules[0].revenue_cagr_min == pytest.approx(0.25)
