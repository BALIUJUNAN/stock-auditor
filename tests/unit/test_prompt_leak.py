from __future__ import annotations

from pathlib import Path

import pytest

PROMPT_DIR = Path(__file__).resolve().parents[2] / "config" / "prompts"

CALIBRATION_NAMES = (
    "康弘药业",
    "华天科技",
    "快意电梯",
    "天娱数科",
    "海洋王",
    "多伦科技",
    "哈药股份",
)
CALIBRATION_CODES = (
    "002773",
    "002185",
    "002774",
    "002354",
    "002724",
    "603528",
    "600664",
)


def _prompt_files() -> list[Path]:
    return sorted(path for path in PROMPT_DIR.rglob("*") if path.is_file())


def test_prompt_directory_is_not_empty() -> None:
    assert _prompt_files()


@pytest.mark.parametrize(
    "token", [*CALIBRATION_NAMES, *CALIBRATION_CODES], ids=None
)
def test_prompts_do_not_contain_calibration_stocks(token: str) -> None:
    hits = [
        path.relative_to(PROMPT_DIR).as_posix()
        for path in _prompt_files()
        if token in path.read_text(encoding="utf-8")
    ]
    assert hits == [], f"提示词目录出现校准股标识 {token}：{hits}"


def test_desensitized_templates_exist() -> None:
    examples = PROMPT_DIR / "examples"
    for name in ("README.md", "tier1_example.md", "tier2_example.md"):
        path = examples / name
        assert path.is_file()
        assert "脱敏" in path.read_text(encoding="utf-8")
