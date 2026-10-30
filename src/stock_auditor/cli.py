"""``sa`` 命令行入口。"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

import typer

from stock_auditor import __version__, paths
from stock_auditor.autostart import (
    AutostartError,
    install_autostart,
    uninstall_autostart,
)
from stock_auditor.calibration import run_calibration
from stock_auditor.config import Settings, get_settings
from stock_auditor.db import apply_migrations, connect, database_path
from stock_auditor.doctor import run_checks
from stock_auditor.feishu import (
    CommandService,
    create_feishu_channel,
    load_feishu_config,
    run_bot,
)
from stock_auditor.ingest import run_backfill, run_ingest
from stock_auditor.ingest.common import normalize_code
from stock_auditor.llm import LlmClient, LlmNotConfiguredError
from stock_auditor.logging import configure_logging
from stock_auditor.package import PackageError, build_package
from stock_auditor.pipeline import (
    PipelineLockedError,
    run_daily,
    run_earnings,
    run_weekly,
)
from stock_auditor.report import load_weekly_markdown
from stock_auditor.serve import start_serve


def _configure_output_encoding() -> None:
    """管道/重定向时统一用 UTF-8，避免 Windows 代码页把中文变成乱码。

    交互式终端保持系统默认编码，避免旧版控制台无法显示 UTF-8。
    """
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty():
            with contextlib.suppress(AttributeError, ValueError):
                stream.reconfigure(encoding="utf-8")


_configure_output_encoding()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"stock-auditor {__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="sa",
    help="基本面选股辅助与智能审计系统命令行工具。",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="显示版本号并退出。",
    ),
) -> None:
    """命令行入口。"""


@app.command()
def init(
    backfill: bool = typer.Option(
        False,
        "--backfill",
        help="回填全市场历史数据（可中断续传）。",
    ),
) -> None:
    """建库并执行未应用的数据库迁移；可选回填历史数据。"""
    configure_logging()
    paths.ensure_data_dirs()
    summary = None
    with connect() as connection:
        applied = apply_migrations(connection)
        typer.echo(f"数据库：{database_path()}")
        if applied:
            versions = ", ".join(f"{version:04d}" for version in applied)
            typer.echo(f"已应用迁移：{versions}")
        else:
            typer.echo("数据库已是最新，无需迁移。")
        if not backfill:
            return
        try:
            summary = run_backfill(connection, get_settings())
        except KeyboardInterrupt:
            typer.echo(
                "已中断，进度已保存；重新执行 sa init --backfill 可继续。",
                err=True,
            )
            raise typer.Exit(code=130) from None
    if summary is None:
        return
    typer.echo("回填结果：")
    for name, count in summary.counts.items():
        typer.echo(f"  {name:<20} {count}")
    if summary.errors:
        failed_steps = len(summary.errors) - summary.code_failures
        typer.echo(
            f"失败 {summary.code_failures} 只股票、{failed_steps} 个步骤；"
            "重新执行会只重试未完成的部分。",
            err=True,
        )
        raise typer.Exit(code=1)


def _parse_codes(raw: str) -> list[str] | None:
    items = [item.strip() for item in raw.split(",") if item.strip()]
    if not items:
        return None
    try:
        return [normalize_code(item) for item in items]
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _optional_llm_client(settings: Settings) -> LlmClient | None:
    try:
        return LlmClient(settings)
    except LlmNotConfiguredError as exc:
        typer.echo(f"{exc}；本次只执行量化重算与卡片推送。", err=True)
        return None


@app.command()
def ingest(
    codes: str = typer.Option(
        "",
        "--codes",
        "-c",
        help="逗号分隔的股票代码；留空采集全市场。",
    ),
) -> None:
    """采集股票池、行情、财务、估值等数据并写入数据库。"""
    configure_logging()
    paths.ensure_data_dirs()
    settings = get_settings()
    with connect() as connection:
        apply_migrations(connection)
        summary = run_ingest(connection, settings, codes=_parse_codes(codes))
    typer.echo("采集结果：")
    for name, count in summary.counts.items():
        typer.echo(f"  {name:<20} {count}")
    if summary.errors:
        typer.echo("以下步骤失败：", err=True)
        for name, message in summary.errors.items():
            typer.echo(f"  {name}: {message}", err=True)
        raise typer.Exit(code=1)


@app.command()
def doctor(
    send_test: bool = typer.Option(
        False,
        "--send-test",
        help="向飞书群发送一张测试卡片。",
    ),
) -> None:
    """逐项检查环境、配置、密钥、网络、数据接口与飞书通道。"""
    configure_logging()
    paths.ensure_data_dirs()
    results = run_checks(send_test=send_test)
    failed = 0
    for result in results:
        if result.ok:
            mark = "通过"
        elif result.required:
            mark = "失败"
            failed += 1
        else:
            mark = "可选"
        typer.echo(f"[{mark}] {result.name}：{result.detail}")
    if failed:
        typer.echo(f"共 {failed} 项检查失败。", err=True)
        raise typer.Exit(code=1)
    typer.echo("全部检查通过。")


@app.command()
def bot() -> None:
    """启动飞书自建应用长连接，接收 /查、/周报、/状态 与卡片按钮回调。"""
    configure_logging()
    paths.ensure_data_dirs()
    config = load_feishu_config()
    if config is None:
        typer.echo("缺少 config/local/feishu.yaml，无法启动长连接。", err=True)
        raise typer.Exit(code=1)
    if config.channel != "app":
        typer.echo("长连接需要 channel: app（自建应用机器人）。", err=True)
        raise typer.Exit(code=1)
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        typer.echo("请设置环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET。", err=True)
        raise typer.Exit(code=1)
    if not config.allowed_chat_ids or not config.allowed_user_ids:
        typer.echo(
            "提示：allowed_chat_ids / allowed_user_ids 留空时不会响应任何指令。",
            err=True,
        )

    settings = get_settings()
    try:
        client = LlmClient(settings)
    except LlmNotConfiguredError as exc:
        client = None
        typer.echo(f"{exc}；/查 将只返回量化结果。", err=True)

    with connect() as connection:
        apply_migrations(connection)
    service = CommandService(
        settings=settings,
        config=config,
        client=client,
        channel=create_feishu_channel(),
    )
    typer.echo("飞书长连接已启动，按 Ctrl+C 退出。")
    try:
        run_bot(service, app_id=app_id, app_secret=app_secret)
    except KeyboardInterrupt:
        typer.echo("已退出。")


@app.command()
def serve() -> None:
    """常驻运行：定时周报/每日任务，并启动飞书长连接。"""
    configure_logging()
    paths.ensure_data_dirs()
    settings = get_settings()
    with connect() as connection:
        apply_migrations(connection)
    typer.echo("常驻服务已启动（Ctrl+C 退出）。")
    start_serve(settings)
    typer.echo("常驻服务已停止。")


autostart_app = typer.Typer(
    name="autostart",
    help="管理开机自启。",
    no_args_is_help=True,
)
app.add_typer(autostart_app, name="autostart")


@autostart_app.command("install")
def autostart_install() -> None:
    """安装开机自启，登录后拉起 ``sa serve``。"""
    try:
        result = install_autostart(project_root=paths.project_root())
    except AutostartError as exc:
        typer.echo(f"安装失败：{exc}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"已安装开机自启：{result.target}")


@autostart_app.command("uninstall")
def autostart_uninstall() -> None:
    """移除开机自启。"""
    try:
        result = uninstall_autostart()
    except AutostartError as exc:
        typer.echo(f"卸载失败：{exc}", err=True)
        raise typer.Exit(code=1) from None
    if result.changed:
        typer.echo(f"已移除开机自启：{result.target}")
    else:
        typer.echo("未发现开机自启配置，无需移除。")


@app.command()
def package(
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="压缩包输出路径；默认为 dist/stock-auditor-<版本>.zip。",
    ),
    include_tests: bool = typer.Option(
        False,
        "--include-tests",
        help="同时打包 tests/（默认不打包，避免测试夹具中的假密钥与样例数据进入交付物）。",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="覆盖已存在的压缩包。",
    ),
) -> None:
    """生成交付压缩包，并扫描密钥与私有数据。"""
    try:
        result = build_package(
            paths.project_root(),
            output=output,
            include_tests=include_tests,
            force=force,
        )
    except PackageError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"已生成：{result.archive}")
    typer.echo(f"文件数：{len(result.files)}；大小：{result.size_bytes} 字节")
    typer.echo(f"SHA256：{result.sha256}")


@app.command()
def calibrate() -> None:
    """对 7 只校准股执行完整的 Tier-1 → Tier-2，并对照期望分段。"""
    configure_logging()
    paths.ensure_data_dirs()
    settings = get_settings()
    try:
        client = LlmClient(settings)
    except LlmNotConfiguredError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None

    with connect() as connection:
        apply_migrations(connection)
        result = run_calibration(connection, settings, client=client)

    typer.echo(f"校准运行：{result.run_id}（数据日期 {result.as_of}）")
    typer.echo(
        f"{'代码':<8}{'名称':<10}{'得分':>6}{'期望段':>10}{'档位':>8}  结果"
    )
    for row in result.rows:
        score = "-" if row.score is None else str(row.score)
        expected = f"{row.low}-{row.high}"
        if row.status != "ok":
            outcome = "失败"
        elif row.in_range:
            outcome = "通过"
        else:
            outcome = "偏离"
        typer.echo(
            f"{row.code:<8}{row.name:<10}{score:>6}{expected:>10}"
            f"{row.tier or '-':>8}  {outcome}"
        )
    typer.echo(
        f"落在期望分段：{result.in_range_count}/{len(result.rows)}；"
        f"失败 {result.failed_count} 只"
    )
    if not result.passed:
        typer.echo("校准未通过：至少需要 5/7 落在期望分段。", err=True)
        raise typer.Exit(code=1)


run_app = typer.Typer(
    name="run",
    help="运行流水线。",
    no_args_is_help=True,
)
app.add_typer(run_app, name="run")


@run_app.command("weekly")
def run_weekly_command(
    run_id: str = typer.Argument(
        "",
        help="与 --resume 搭配，指定要续跑的运行编号；留空续跑最近一次未成功的运行。",
    ),
    until: str = typer.Option(
        "S8",
        "--until",
        help="执行到哪一步（S1~S8）。",
    ),
    codes: str = typer.Option(
        "",
        "--codes",
        "-c",
        help="只跑指定股票，逗号分隔；留空跑全市场。",
    ),
    refresh: bool = typer.Option(
        False,
        "--refresh",
        help="先执行 S1 数据刷新（联网采集）。",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help=(
            "续跑运行。单独使用续跑最近一次未成功的运行；"
            "后接运行编号（--resume RUN_ID）续跑指定运行。"
        ),
    ),
    push: bool = typer.Option(
        True,
        "--push/--no-push",
        help="是否推送飞书卡片（未配置飞书时自动跳过）。",
    ),
) -> None:
    """执行周日流水线 S1~S8，生成量化校准报告与周报。"""
    if run_id and not resume:
        typer.echo("指定运行编号时必须同时使用 --resume。", err=True)
        raise typer.Exit(code=2)
    configure_logging()
    paths.ensure_data_dirs()
    settings = get_settings()
    with connect() as connection:
        apply_migrations(connection)
        try:
            result = run_weekly(
                connection,
                settings,
                until=until,
                codes=_parse_codes(codes),
                refresh=refresh,
                resume=run_id if resume and run_id else resume,
                push=push,
            )
        except PipelineLockedError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from None
        except (ValueError, RuntimeError) as exc:
            typer.echo(f"流水线失败：{exc}", err=True)
            raise typer.Exit(code=1) from None
    typer.echo(f"运行编号：{result.run_id}")
    typer.echo(f"数据日期：{result.as_of}")
    typer.echo(
        f"股票池 {result.universe_count} 只；"
        f"Stage 0 通过 {result.stage0_passed_count} 只；"
        f"硬 Veto {result.hard_veto_count} 只；"
        f"LLM 池 {len(result.pool)} 只；"
        f"审计成功 {result.audit_ok_count} 只 / 失败 {result.audit_failed_count} 只"
    )
    if result.llm_skipped:
        typer.echo(
            f"模型审计未执行（{result.llm_skip_reason or 'LLM 未配置'}）；"
            "本次仅输出量化结果。"
        )
    if result.quant_check_path is not None:
        typer.echo(f"量化校准报告：{result.quant_check_path}")
    if result.report_path is not None:
        typer.echo(f"周报：{result.report_path}")
    if result.chart_path is not None:
        typer.echo(f"图表：{result.chart_path}")


@run_app.command("daily")
def run_daily_command(
    codes: str = typer.Option(
        "",
        "--codes",
        "-c",
        help="手动指定核心池，逗号分隔；留空使用关注名单 + 周报四星股。",
    ),
    push: bool = typer.Option(
        True,
        "--push/--no-push",
        help="是否推送飞书告警卡片（未配置飞书时自动跳过）。",
    ),
) -> None:
    """扫描核心池异动并检查财报节点，必要时重跑 S5~S8。"""
    configure_logging()
    paths.ensure_data_dirs()
    settings = get_settings()
    client = _optional_llm_client(settings)
    with connect() as connection:
        apply_migrations(connection)
        try:
            result = run_daily(
                connection,
                settings,
                codes=_parse_codes(codes),
                client=client,
                push=push,
            )
        except PipelineLockedError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from None
        except (ValueError, RuntimeError) as exc:
            typer.echo(f"每日流水线失败：{exc}", err=True)
            raise typer.Exit(code=1) from None
    typer.echo(f"运行编号：{result.run_id}")
    typer.echo(f"数据日期：{result.as_of}")
    typer.echo(
        f"核心池 {len(result.pool)} 只；触发 {len(result.triggers)} 只；"
        f"本周忽略 {len(result.ignored)} 只"
    )
    for trigger in result.triggers:
        typer.echo(f"  {trigger.code} {trigger.name}：{'；'.join(trigger.reasons)}")
    typer.echo(
        f"财报提醒 {len(result.earnings_warnings)} 只；"
        f"T+1 重算 {len(result.earnings_recalculated)} 只；"
        f"已推送 {result.pushed_count} 张卡片"
    )


@run_app.command("earnings")
def run_earnings_command(
    codes: str = typer.Option(
        "",
        "--codes",
        "-c",
        help="只检查指定股票，逗号分隔；留空使用核心池。",
    ),
    push: bool = typer.Option(
        True,
        "--push/--no-push",
        help="是否推送飞书卡片（未配置飞书时自动跳过）。",
    ),
) -> None:
    """执行财报提醒与披露后 T+1 全量重算。"""
    configure_logging()
    paths.ensure_data_dirs()
    settings = get_settings()
    client = _optional_llm_client(settings)
    with connect() as connection:
        apply_migrations(connection)
        try:
            result = run_earnings(
                connection,
                settings,
                codes=_parse_codes(codes),
                client=client,
                push=push,
            )
        except PipelineLockedError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from None
        except (ValueError, RuntimeError) as exc:
            typer.echo(f"财报流水线失败：{exc}", err=True)
            raise typer.Exit(code=1) from None
    typer.echo(f"运行编号：{result.run_id}")
    typer.echo(f"数据日期：{result.as_of}")
    for warning in result.warnings:
        typer.echo(
            f"  {warning.code} {warning.name}：{warning.scheduled_date} 披露"
            f"（{warning.trading_days} 个交易日内）"
        )
    typer.echo(
        f"财报提醒 {len(result.warnings)} 只；"
        f"到期重算 {len(result.due)} 只；"
        f"已完成 {len(result.recalculated)} 只；"
        f"已推送 {result.pushed_count} 张卡片"
    )


report_app = typer.Typer(
    name="report",
    help="查看已生成的报告。",
    no_args_is_help=True,
)
app.add_typer(report_app, name="report")


@report_app.command("show")
def report_show(
    run_id: str = typer.Argument(..., help="运行编号，例如 weekly-20261030-120000。"),
) -> None:
    """输出指定运行的周报 Markdown。"""
    with connect() as connection:
        apply_migrations(connection)
        markdown = load_weekly_markdown(connection, run_id)
    if markdown is None:
        typer.echo(f"找不到周报：{run_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(markdown, nl=False)
