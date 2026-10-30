"""同一条流水线禁止并发运行（``var/locks/`` 文件锁）。"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from types import TracebackType

from stock_auditor import paths


class PipelineLockedError(RuntimeError):
    """已有同一条流水线在运行。"""


class FileLock:
    def __init__(self, pipeline: str, *, directory: Path | None = None) -> None:
        base = Path(directory) if directory is not None else paths.locks_dir()
        self.pipeline = pipeline
        self.path = base / f"{pipeline}.lock"
        self._fd: int | None = None

    def __enter__(self) -> FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            raise PipelineLockedError(
                f"流水线 {self.pipeline} 已在运行（锁文件：{self.path}）。"
                "如确认上次异常退出，请删除该锁文件后重试。"
            ) from exc
        os.write(
            self._fd,
            f"pid={os.getpid()} started={datetime.now().isoformat()}\n".encode(),
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        self.path.unlink(missing_ok=True)
