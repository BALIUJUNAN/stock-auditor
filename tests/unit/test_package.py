"""T3.6：交付打包白名单、密钥扫描与私有数据扫描。"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from stock_auditor.package import PackageError, build_package, iter_package_files


def _write(root: Path, name: str, text: str = "") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    _write(root, "pyproject.toml", '[project]\nname = "stock-auditor"\n')
    _write(root, "README.md", "# demo\n")
    _write(root, "LICENSE", "MIT\n")
    _write(root, "CHANGELOG.md", "# 0.1.0\n")
    _write(root, "uv.lock", "# lock\n")
    _write(root, ".python-version", "3.12\n")
    _write(root, ".gitignore", "var/\n")
    _write(root, ".env.example", "LLM_API_KEY=\nFEISHU_APP_SECRET=\n")
    _write(root, "install.ps1", "Write-Host ok\n")
    _write(root, "install.sh", "#!/usr/bin/env bash\n")
    _write(root, "src/stock_auditor/__init__.py", '__version__ = "0.1.0"\n')
    _write(root, "config/settings.yaml", 'schedule:\n  weekly: "sun 20:00"\n')
    _write(root, "config/prompts/tier1_extract.md", "只输出 JSON。\n")
    _write(root, "config/local/feishu.example.yaml", 'channel: app\nchat_id: ""\n')
    _write(root, "config/local/feishu.yaml", "channel: app\nchat_id: oc_private\n")
    _write(root, "migrations/0001_init.sql", "SELECT 1;\n")
    _write(root, "docs/DECISIONS.md", "# 决策\n")
    _write(root, "docs/data_sources.md", "# 内部探测记录\n")
    _write(root, "docs/SPEC_RECONCILIATION.md", "# 内部规划\n")
    _write(root, "docs/OPEN_QUESTIONS.md", "# 内部问题\n")
    _write(root, "scripts/probe.py", "print('ok')\n")
    _write(root, "tests/unit/test_demo.py", "def test_ok():\n    assert True\n")
    _write(root, ".env", "LLM_API_KEY=real-value\n")
    _write(root, "var/db/stock.duckdb", "binary")
    _write(root, "src/stock_auditor/__pycache__/x.pyc", "cache")
    _write(root, "dist/old.zip", "zip")
    return root


def test_iter_package_files_excludes_private_and_cache(tmp_path: Path) -> None:
    root = _project(tmp_path)
    names = {path.relative_to(root).as_posix() for path in iter_package_files(root)}

    assert "pyproject.toml" in names
    assert "src/stock_auditor/__init__.py" in names
    assert "config/prompts/tier1_extract.md" in names
    assert "config/local/feishu.example.yaml" in names
    assert "migrations/0001_init.sql" in names
    assert "docs/DECISIONS.md" in names
    assert "install.sh" in names

    assert ".env" not in names
    assert "config/local/feishu.yaml" not in names
    assert "docs/data_sources.md" not in names
    assert "docs/SPEC_RECONCILIATION.md" not in names
    assert "docs/OPEN_QUESTIONS.md" not in names
    assert "tests/unit/test_demo.py" not in names
    assert not any(name.startswith("var/") for name in names)
    assert not any("__pycache__" in name for name in names)
    assert not any(name.startswith("dist/") for name in names)


def test_build_package_writes_zip_with_scanned_files(tmp_path: Path) -> None:
    root = _project(tmp_path)
    archive = tmp_path / "out" / "stock-auditor.zip"

    result = build_package(root, output=archive)

    assert result.archive == archive
    assert archive.exists()
    assert result.size_bytes == archive.stat().st_size
    assert len(result.sha256) == 64
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == set(result.files)
        assert "config/local/feishu.example.yaml" in bundle.namelist()
        assert "config/local/feishu.yaml" not in bundle.namelist()


def test_build_package_blocks_real_secret(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _write(root, "src/stock_auditor/bad.py", "LLM_API_KEY=" + "sk-" + "a" * 24 + "\n")

    with pytest.raises(PackageError) as caught:
        build_package(root, output=tmp_path / "pkg.zip")

    problems = caught.value.problems
    assert any(
        problem.kind == "secret" and problem.path == "src/stock_auditor/bad.py"
        for problem in problems
    )
    assert not (tmp_path / "pkg.zip").exists()


def test_build_package_blocks_feishu_webhook(tmp_path: Path) -> None:
    root = _project(tmp_path)
    webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/" + "abc12345-6789"
    _write(root, "docs/SETUP.md", f"Webhook：{webhook}\n")

    with pytest.raises(PackageError) as caught:
        build_package(root, output=tmp_path / "pkg.zip")

    assert any(problem.kind == "secret" for problem in caught.value.problems)


def test_build_package_allows_placeholders(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _write(
        root,
        ".env.example",
        "LLM_API_KEY=your-api-key\n"
        "FEISHU_APP_SECRET=<your-secret>\n"
        "TUSHARE_TOKEN=${TUSHARE_TOKEN}\n"
        "COMMERCIAL_PASSWORD=changeme\n",
    )

    result = build_package(root, output=tmp_path / "pkg.zip")

    assert ".env.example" in result.files


def test_build_package_blocks_calibration_identifiers_in_prompts(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _write(root, "config/prompts/tier2_audit.md", "参考 002773 与 康弘药业。\n")

    with pytest.raises(PackageError) as caught:
        build_package(root, output=tmp_path / "pkg.zip")

    details = [
        problem.detail
        for problem in caught.value.problems
        if problem.kind == "private"
    ]
    assert any("002773" in detail for detail in details)
    assert any("康弘药业" in detail for detail in details)


def test_build_package_blocks_any_stock_code_in_prompts(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _write(root, "config/prompts/examples/sample.md", "示例代码 600519。\n")

    with pytest.raises(PackageError) as caught:
        build_package(root, output=tmp_path / "pkg.zip")

    assert any(problem.kind == "private" for problem in caught.value.problems)


def test_build_package_requires_force_to_overwrite(tmp_path: Path) -> None:
    root = _project(tmp_path)
    archive = tmp_path / "pkg.zip"
    build_package(root, output=archive)

    with pytest.raises(PackageError) as caught:
        build_package(root, output=archive)

    assert caught.value.problems[0].kind == "path"
    assert build_package(root, output=archive, force=True).archive == archive


def test_include_tests_is_opt_in(tmp_path: Path) -> None:
    root = _project(tmp_path)

    default = build_package(root, output=tmp_path / "default.zip")
    with_tests = build_package(root, output=tmp_path / "tests.zip", include_tests=True)

    assert "tests/unit/test_demo.py" not in default.files
    assert "tests/unit/test_demo.py" in with_tests.files


def test_build_package_rejects_missing_project(tmp_path: Path) -> None:
    with pytest.raises(PackageError):
        build_package(tmp_path / "missing", output=tmp_path / "pkg.zip")
