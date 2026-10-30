from __future__ import annotations

from pathlib import Path

import pytest

from stock_auditor import paths


def test_sa_home_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "data"
    monkeypatch.setenv("SA_HOME", str(target))

    assert paths.data_root() == target.resolve()
    assert paths.logs_dir() == target.resolve() / "logs"
    assert paths.db_dir() == target.resolve() / "db"


def test_default_data_root_is_project_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SA_HOME", raising=False)

    assert paths.data_root() == paths.project_root() / "var"


def test_ensure_data_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "home"
    monkeypatch.setenv("SA_HOME", str(target))

    root = paths.ensure_data_dirs()

    assert root == target.resolve()
    for name in paths.DATA_DIR_NAMES:
        assert (root / name).is_dir()
