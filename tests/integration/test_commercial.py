"""商业源适配器集成测试。

没有账号时必须返回「未配置」且不报错；有账号时抓取真实财务数据，
并在数据库已有开源源财务数据时跑一遍交叉验证。
"""

from __future__ import annotations

from datetime import date

from stock_auditor.commercial import FinancialRecord, create_commercial_source, cross_validate
from stock_auditor.config import get_settings
from stock_auditor.db.connection import connect, database_path

CODES = ("002773", "002185")


def _load_open_records(codes: tuple[str, ...]) -> list[FinancialRecord]:
    if not database_path().exists():
        return []
    placeholders = ", ".join("?" for _ in codes)
    with connect(read_only=True) as connection:
        rows = connection.execute(
            f"""
            SELECT code, report_period, revenue, net_profit_parent, ocf
            FROM financials
            WHERE source = 'akshare' AND code IN ({placeholders})
            """,
            list(codes),
        ).fetchall()
    return [
        FinancialRecord(
            code=row[0],
            report_period=row[1],
            revenue=row[2],
            net_profit_parent=row[3],
            ocf=row[4],
        )
        for row in rows
        if isinstance(row[1], date)
    ]


def test_commercial_source_handles_both_states() -> None:
    settings = get_settings()
    source = create_commercial_source(settings)

    if not source.configured:
        assert "未配置" in source.status
        assert source.fetch_financials(CODES, periods=4) == []
        return

    records = source.fetch_financials(CODES, periods=settings.ingest.financial_periods)
    assert records, "商业源已配置，但没有返回任何财务数据"
    for record in records:
        assert record.code in CODES
        assert isinstance(record.report_period, date)
        assert any(
            value is not None
            for value in (record.revenue, record.net_profit_parent, record.ocf)
        )

    open_records = _load_open_records(CODES)
    if not open_records:
        return
    validation = settings.data_quality.cross_validation
    flags = cross_validate(
        list(CODES),
        open_records,
        records,
        max_deviation=validation.max_deviation,
        missing_label=validation.missing_label,
        suspect_label=validation.suspect_label,
    )
    assert set(flags) == set(CODES)
