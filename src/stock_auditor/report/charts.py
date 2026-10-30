"""周报得分图：matplotlib 渲染 PNG，供本地查看与飞书图片上传。

仅使用非交互后端 ``Agg``；matplotlib 在函数内延迟导入，避免拖慢其他命令。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# 按平台常见程度排序；Windows 自带微软雅黑/黑体，Linux 常用 Noto/文泉驿。
_CJK_FONTS: tuple[str, ...] = (
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Zen Hei",
    "DejaVu Sans",
)


def _score_of(row: dict[str, Any]) -> float | None:
    for key in ("final_total", "quant_total"):
        value = row.get(key)
        if value is not None:
            return float(value)
    return None


def _bar_color(score: float) -> str:
    if score >= 70:
        return "#2f9e44"
    if score >= 60:
        return "#1971c2"
    if score >= 50:
        return "#f08c00"
    return "#868e96"


def _pick_font(available: set[str]) -> str:
    for name in _CJK_FONTS:
        if name in available:
            return name
    return "DejaVu Sans"


def render_weekly_chart(
    payload: dict[str, Any],
    output_path: Path,
    *,
    top_n: int = 10,
) -> Path | None:
    """渲染周报 Top N 得分横向柱状图；无得分数据时返回 ``None``。"""
    items: list[tuple[str, str, float]] = []
    for row in payload.get("top") or []:
        score = _score_of(row)
        if score is None:
            continue
        name = str(row.get("name") or "")
        code = str(row.get("code") or "")
        label = f"{name}（{code}）" if name and code else (name or code)
        items.append((label, code, score))
        if len(items) >= top_n:
            break
    if not items:
        log.info("weekly.chart.empty")
        return None

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    available = {font.name for font in font_manager.fontManager.ttflist}
    font = _pick_font(available)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    scores = [score for _, _, score in items]
    labels = [label for label, _, _ in items]
    colors = [_bar_color(score) for score in scores]
    height = max(3.2, 0.45 * len(items) + 1.6)

    with plt.rc_context({"font.sans-serif": [font], "axes.unicode_minus": False}):
        fig, ax = plt.subplots(figsize=(8.0, height), dpi=150)
        try:
            positions = list(range(len(items)))
            bars = ax.barh(positions, scores, color=colors, height=0.62)
            ax.set_yticks(positions, labels)
            ax.invert_yaxis()
            ax.set_xlim(0, max(100.0, max(scores) + 12.0))
            ax.set_xlabel("综合得分")
            ax.grid(axis="x", color="#dee2e6", linewidth=0.8)
            ax.set_axisbelow(True)
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
            for bar, score in zip(bars, scores, strict=True):
                ax.text(
                    score + 1.0,
                    bar.get_y() + bar.get_height() / 2,
                    f"{score:g}",
                    va="center",
                    fontsize=9,
                    color="#495057",
                )
            suffix = "（模型审计未执行）" if payload.get("audit_skipped") else ""
            as_of = str(payload.get("as_of") or "")
            ax.set_title(
                f"周报得分 Top {len(items)} · {as_of}{suffix}",
                fontsize=13,
                fontweight="bold",
                loc="left",
                pad=12,
            )
            fig.tight_layout()
            fig.savefig(output_path, bbox_inches="tight", facecolor="white")
        finally:
            plt.close(fig)

    log.info("weekly.chart.rendered", path=str(output_path), items=len(items))
    return output_path
