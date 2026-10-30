"""运行上下文：``run_id``、步骤状态与 ``run_log`` 落库。

``run_id`` 格式为 ``{pipeline}-{YYYYMMDD-HHMMSS}``（任务书 5.3 节）。
步骤状态以 JSON 写入 ``run_log.step_status``，供 T3.1 的断点续跑读取。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

import duckdb

_STATUS_RUNNING = "running"
_STATUS_SUCCESS = "success"
_STATUS_FAILED = "failed"

_SAVE_SQL = """
INSERT OR REPLACE INTO run_log
    (run_id, pipeline, started_at, finished_at, status, step_status,
     llm_tokens, llm_cost, error)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def new_run_id(pipeline: str, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"{pipeline}-{stamp}"


@dataclass
class RunContext:
    run_id: str
    pipeline: str
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None
    status: str = _STATUS_RUNNING
    error: str | None = None
    step_status: dict[str, str] = field(default_factory=dict)
    llm_tokens: int = 0
    llm_cost: float = 0.0

    @classmethod
    def start(
        cls,
        pipeline: str,
        *,
        now: datetime | None = None,
    ) -> RunContext:
        moment = now or datetime.now()
        return cls(
            run_id=new_run_id(pipeline, moment),
            pipeline=pipeline,
            started_at=moment,
        )

    def begin_step(self, step: str) -> None:
        self.step_status[step] = _STATUS_RUNNING

    def complete_step(self, step: str) -> None:
        self.step_status[step] = "done"

    def warn_step(self, step: str, message: str) -> None:
        self.step_status[step] = f"warning: {message}"

    def fail_step(self, step: str, message: str) -> None:
        self.step_status[step] = f"failed: {message}"

    def finish(self) -> None:
        self.status = (
            "partial"
            if any(value.startswith("failed") for value in self.step_status.values())
            else _STATUS_SUCCESS
        )
        self.finished_at = datetime.now()

    def fail(self, message: str) -> None:
        self.status = _STATUS_FAILED
        self.error = message
        self.finished_at = datetime.now()

    def add_usage(self, tokens: int, cost: float) -> None:
        self.llm_tokens += tokens
        self.llm_cost += cost

    def save(self, connection: duckdb.DuckDBPyConnection) -> None:
        connection.execute(
            _SAVE_SQL,
            [
                self.run_id,
                self.pipeline,
                self.started_at,
                self.finished_at,
                self.status,
                json.dumps(self.step_status, ensure_ascii=False),
                self.llm_tokens,
                self.llm_cost,
                self.error,
            ],
        )
