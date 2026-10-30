from __future__ import annotations

import json
from pathlib import Path

import structlog

from stock_auditor.logging import configure_logging


def test_json_log_written_to_file(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "app.log"
    configure_logging(level="INFO", log_file=log_file)

    structlog.get_logger("test").info("hello", answer=42)

    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    record = json.loads(lines[-1])
    assert record["event"] == "hello"
    assert record["answer"] == 42
    assert record["level"] == "info"
