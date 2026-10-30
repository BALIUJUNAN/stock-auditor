"""提示词文件加载：读取头部 ``version:`` 与正文模板。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from stock_auditor import paths

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class PromptError(ValueError):
    """提示词文件缺失、缺少版本号或格式错误。"""


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    body: str


def load_prompt(name: str, *, directory: Path | None = None) -> PromptTemplate:
    base = Path(directory) if directory is not None else paths.config_dir() / "prompts"
    path = base / f"{name}.md"
    if not path.is_file():
        raise PromptError(f"提示词文件不存在：{path}")
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(text)
    if match is None:
        raise PromptError(f"提示词缺少 YAML 头部：{path}")
    try:
        metadata = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise PromptError(f"提示词头部不是合法 YAML：{path}") from exc
    version = str(metadata.get("version", "")).strip()
    if not version:
        raise PromptError(f"提示词缺少 version 字段：{path}")
    return PromptTemplate(
        name=name,
        version=version,
        body=text[match.end() :],
    )


def render_prompt(template: PromptTemplate, **values: object) -> str:
    body = template.body
    for key, value in values.items():
        body = body.replace("{{" + key + "}}", str(value))
    return body
