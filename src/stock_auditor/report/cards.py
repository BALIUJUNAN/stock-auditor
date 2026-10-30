"""飞书卡片 JSON 2.0：Jinja2 模板渲染（任务书 14.2 节）。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_CARD_DIR = Path(__file__).resolve().parent / "cards"
_ENV = Environment(
    loader=FileSystemLoader(str(_CARD_DIR)),
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=False,
)


def _render(template_name: str, **context: Any) -> dict[str, Any]:
    text = _ENV.get_template(template_name).render(**context)
    return json.loads(text)


def build_main_card(
    payload: dict[str, Any],
    *,
    show_button: bool = True,
    image_key: str | None = None,
) -> dict[str, Any]:
    return _render(
        "main.j2",
        report=payload,
        show_button=show_button,
        image_key=image_key,
    )


def build_detail_card(row: dict[str, Any]) -> dict[str, Any]:
    return _render("detail.j2", row=row)


def build_alert_card(
    *,
    code: str,
    name: str,
    title: str,
    detail: str,
    as_of: str,
    buttons: Sequence[dict[str, str]] = (),
) -> dict[str, Any]:
    return _render(
        "alert.j2",
        code=code,
        name=name,
        title=title,
        detail=detail,
        as_of=as_of,
        buttons=list(buttons),
    )


def build_text_card(
    *,
    title: str,
    markdown: str,
    template: str = "blue",
) -> dict[str, Any]:
    return _render(
        "text.j2",
        title=title,
        markdown=markdown,
        template=template,
    )


def build_receipt_card(
    *,
    run_id: str,
    status: str,
    duration: str,
    llm_tokens: int,
    llm_cost: float,
) -> dict[str, Any]:
    return _render(
        "receipt.j2",
        run_id=run_id,
        status=status,
        duration=duration,
        llm_tokens=llm_tokens,
        llm_cost=llm_cost,
    )
