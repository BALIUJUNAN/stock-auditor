"""报告生成：量化校准检查与周报。"""

from stock_auditor.report.cards import (
    build_alert_card,
    build_detail_card,
    build_main_card,
    build_receipt_card,
    build_text_card,
)
from stock_auditor.report.charts import render_weekly_chart
from stock_auditor.report.quant_check import (
    CALIBRATION_CODES,
    QuantCheckRow,
    render_quant_check,
    write_quant_check,
)
from stock_auditor.report.weekly import (
    WeeklyReport,
    WeeklyRow,
    build_weekly_report,
    collect_weekly_rows,
    load_weekly_markdown,
    render_detail_markdown,
    render_weekly_markdown,
)

__all__ = [
    "CALIBRATION_CODES",
    "QuantCheckRow",
    "WeeklyReport",
    "WeeklyRow",
    "build_alert_card",
    "build_detail_card",
    "build_main_card",
    "build_receipt_card",
    "build_text_card",
    "build_weekly_report",
    "collect_weekly_rows",
    "load_weekly_markdown",
    "render_detail_markdown",
    "render_quant_check",
    "render_weekly_chart",
    "render_weekly_markdown",
    "write_quant_check",
]
