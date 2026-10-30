"""常驻服务：APScheduler 定时任务 + 飞书长连接单进程运行。

调度时间来自 ``settings.schedule``（如 ``sun 20:00``、``mon-fri 16:30``）。
进程启动时会补跑最近一次错过且仍在 ``misfire_grace_hours`` 窗口内的任务。
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import time as clock_time
from zoneinfo import ZoneInfo

import duckdb
import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from stock_auditor.config import Settings
from stock_auditor.db import apply_migrations, connect
from stock_auditor.feishu import (
    CommandService,
    create_feishu_channel,
    load_feishu_config,
    run_bot,
)
from stock_auditor.ingest import run_ingest
from stock_auditor.llm import LlmClient, LlmNotConfiguredError
from stock_auditor.pipeline import run_daily, run_weekly

log = structlog.get_logger(__name__)

_DAY_NAMES = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}
_SCHEDULE_PATTERN = re.compile(
    r"^(?P<days>[a-z]{3}(?:-[a-z]{3})?)\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})$"
)
_WEEKLY = "weekly"
_DAILY = "daily"

ConnectionFactory = Callable[[], AbstractContextManager[duckdb.DuckDBPyConnection]]
Runner = Callable[[], None]


@dataclass(frozen=True)
class ScheduleSpec:
    day_of_week: str
    weekdays: frozenset[int]
    hour: int
    minute: int

    def time(self) -> clock_time:
        return clock_time(self.hour, self.minute)


def parse_schedule(spec: str) -> ScheduleSpec:
    """解析 ``sun 20:00`` / ``mon-fri 16:30`` 形式的调度表达式。"""
    match = _SCHEDULE_PATTERN.match(spec.strip().lower())
    if match is None:
        raise ValueError(f"无法解析调度表达式：{spec!r}（示例：sun 20:00）")
    raw_days = match.group("days")
    if "-" in raw_days:
        start_name, end_name = raw_days.split("-", 1)
        start = _DAY_NAMES.get(start_name)
        end = _DAY_NAMES.get(end_name)
        if start is None or end is None:
            raise ValueError(f"未知星期：{raw_days}")
        weekdays = (
            set(range(start, end + 1))
            if start <= end
            else set(range(start, 7)) | set(range(0, end + 1))
        )
    else:
        weekday = _DAY_NAMES.get(raw_days)
        if weekday is None:
            raise ValueError(f"未知星期：{raw_days}")
        weekdays = {weekday}
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"时间超出范围：{spec!r}")
    return ScheduleSpec(
        day_of_week=raw_days,
        weekdays=frozenset(weekdays),
        hour=hour,
        minute=minute,
    )


def latest_occurrence(spec: ScheduleSpec, now: datetime) -> datetime:
    """返回 ``now`` 之前最近一次计划执行时间（按星期近似，不含节假日）。"""
    for offset in range(8):
        candidate_date = now.date() - timedelta(days=offset)
        if candidate_date.weekday() not in spec.weekdays:
            continue
        candidate = datetime.combine(
            candidate_date,
            spec.time(),
            tzinfo=now.tzinfo,
        )
        if candidate <= now:
            return candidate
    raise ValueError(f"无法计算最近一次执行时间：{spec!r}")


def _has_successful_run_since(
    connection: duckdb.DuckDBPyConnection,
    pipeline: str,
    since: datetime,
) -> bool:
    row = connection.execute(
        "SELECT 1 FROM run_log WHERE pipeline = ? AND status = 'success' "
        "AND started_at >= ? LIMIT 1",
        [pipeline, since],
    ).fetchone()
    return row is not None


def catch_up_pipelines(
    connection: duckdb.DuckDBPyConnection,
    settings: Settings,
    *,
    now: datetime,
    runners: Mapping[str, Runner],
) -> tuple[str, ...]:
    """补跑最近一次错过且仍在宽限窗口内的任务，返回已执行的流水线名。"""
    grace = timedelta(hours=settings.schedule.misfire_grace_hours)
    executed: list[str] = []
    for pipeline, expression in (
        (_WEEKLY, settings.schedule.weekly),
        (_DAILY, settings.schedule.daily),
    ):
        runner = runners.get(pipeline)
        if runner is None:
            continue
        occurrence = latest_occurrence(parse_schedule(expression), now)
        if now - occurrence > grace:
            continue
        if _has_successful_run_since(connection, pipeline, occurrence):
            continue
        try:
            runner()
        except Exception as exc:  # noqa: BLE001 - 单个补跑失败不阻塞服务启动
            log.error(
                "serve.catch_up_failed",
                pipeline=pipeline,
                occurrence=occurrence.isoformat(),
                error=str(exc),
            )
            continue
        executed.append(pipeline)
        log.info(
            "serve.catch_up",
            pipeline=pipeline,
            occurrence=occurrence.isoformat(),
        )
    return tuple(executed)


def default_runners(settings: Settings) -> dict[str, Runner]:
    """构造默认任务：周报刷新数据；每日先采集再扫描。"""

    def weekly() -> None:
        with connect() as connection:
            apply_migrations(connection)
            run_weekly(connection, settings, refresh=True)

    def daily() -> None:
        with connect() as connection:
            apply_migrations(connection)
            summary = run_ingest(connection, settings)
            if summary.errors:
                log.warning("serve.daily_ingest_errors", errors=summary.errors)
            try:
                client = LlmClient(settings)
            except LlmNotConfiguredError as exc:
                log.warning("serve.daily_llm_skipped", reason=str(exc))
                client = None
            data_errors = dict(summary.errors)
            if summary.warnings.get("announcement_text"):
                data_errors["announcement_text"] = summary.warnings["announcement_text"]
            run_daily(connection, settings, client=client, ingest_errors=data_errors)

    return {_WEEKLY: weekly, _DAILY: daily}


def build_scheduler(
    settings: Settings,
    *,
    runners: Mapping[str, Runner],
) -> BackgroundScheduler:
    """创建 APScheduler 实例；任务默认合并补跑并限制单实例。"""
    timezone = ZoneInfo(settings.schedule.timezone)
    grace = settings.schedule.misfire_grace_hours * 3600
    scheduler = BackgroundScheduler(
        timezone=timezone,
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": grace,
        },
    )
    for pipeline, expression in (
        (_WEEKLY, settings.schedule.weekly),
        (_DAILY, settings.schedule.daily),
    ):
        runner = runners.get(pipeline)
        if runner is None:
            continue
        spec = parse_schedule(expression)
        scheduler.add_job(
            runner,
            CronTrigger(
                day_of_week=spec.day_of_week,
                hour=spec.hour,
                minute=spec.minute,
                timezone=timezone,
            ),
            id=pipeline,
            name=pipeline,
            replace_existing=True,
        )
    return scheduler


def _default_bot_runner(settings: Settings) -> Runner | None:
    """飞书 app 通道配置齐全时，返回长连接线程体；否则跳过。"""
    config = load_feishu_config()
    if config is None or config.channel != "app":
        return None
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        log.warning("serve.bot_skipped", reason="缺少 FEISHU_APP_ID/FEISHU_APP_SECRET")
        return None
    try:
        client = LlmClient(settings)
    except LlmNotConfiguredError:
        client = None
    service = CommandService(
        settings=settings,
        config=config,
        client=client,
        channel=create_feishu_channel(),
    )

    def bot() -> None:
        run_bot(service, app_id=app_id, app_secret=app_secret)

    return bot


def _start_bot(runner: Runner) -> threading.Thread:
    thread = threading.Thread(target=runner, name="feishu-bot", daemon=True)
    thread.start()
    return thread


@dataclass
class ServeRuntime:
    scheduler: BackgroundScheduler
    caught_up: tuple[str, ...]
    bot_thread: threading.Thread | None = None
    stopped: bool = field(default=False, init=False)

    def stop(self) -> None:
        if self.stopped:
            return
        self.stopped = True
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001 - 关闭阶段的异常不影响退出
            log.exception("serve.scheduler_shutdown_failed")


def start_serve(
    settings: Settings,
    *,
    now: datetime | None = None,
    block: bool = True,
    runners: Mapping[str, Runner] | None = None,
    bot_runner: Runner | None = None,
    start_bot: bool = True,
    catch_up: bool = True,
    connection_factory: ConnectionFactory = connect,
) -> ServeRuntime:
    """启动调度器与飞书长连接；``block=True`` 时阻塞到 Ctrl+C。"""
    moment = now or datetime.now()
    resolved = dict(runners) if runners is not None else default_runners(settings)

    caught_up: tuple[str, ...] = ()
    if catch_up:
        with connection_factory() as connection:
            caught_up = catch_up_pipelines(
                connection,
                settings,
                now=moment,
                runners=resolved,
            )

    scheduler = build_scheduler(settings, runners=resolved)
    scheduler.start()
    log.info(
        "serve.start",
        jobs=[job.id for job in scheduler.get_jobs()],
        caught_up=list(caught_up),
    )

    selected_bot = bot_runner
    if start_bot and selected_bot is None:
        selected_bot = _default_bot_runner(settings)
    thread = _start_bot(selected_bot) if selected_bot is not None else None

    runtime = ServeRuntime(
        scheduler=scheduler,
        caught_up=caught_up,
        bot_thread=thread,
    )
    if block:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            log.info("serve.interrupted")
        finally:
            runtime.stop()
    return runtime
