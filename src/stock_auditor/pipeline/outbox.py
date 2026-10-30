"""Durable at-least-once delivery for alert cards."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import duckdb

from stock_auditor.feishu.base import FeishuChannel, FeishuError


def _ensure(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS alert_outbox (
        id VARCHAR PRIMARY KEY, payload VARCHAR NOT NULL, status VARCHAR NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, error VARCHAR,
        created_at TIMESTAMP DEFAULT current_timestamp, delivered_at TIMESTAMP)""")


def enqueue(connection: duckdb.DuckDBPyConnection, card: dict[str, Any], *, key: str) -> str:
    _ensure(connection)
    payload = json.dumps(card, ensure_ascii=False, sort_keys=True)
    identifier = hashlib.sha256(key.encode()).hexdigest()
    connection.execute(
        "INSERT INTO alert_outbox (id, payload, status) "
        "VALUES (?, ?, 'pending') ON CONFLICT DO NOTHING",
        [identifier, payload],
    )
    return identifier


def deliver(connection: duckdb.DuckDBPyConnection, channel: FeishuChannel | None) -> int:
    _ensure(connection)
    if channel is None or not channel.configured:
        return 0
    sent = 0
    rows = connection.execute(
        "SELECT id, payload FROM alert_outbox WHERE status = 'pending' ORDER BY created_at, id"
    ).fetchall()
    for identifier, payload in rows:
        try:
            channel.send_card(json.loads(payload))
        except FeishuError as exc:
            connection.execute(
                "UPDATE alert_outbox SET attempts = attempts + 1, error = ? WHERE id = ?",
                [str(exc), identifier],
            )
        else:
            connection.execute(
                "UPDATE alert_outbox SET status = 'sent', attempts = attempts + 1, "
                "error = NULL, delivered_at = current_timestamp WHERE id = ?",
                [identifier],
            )
            sent += 1
    return sent


def pending_count(connection: duckdb.DuckDBPyConnection) -> int:
    _ensure(connection)
    return connection.execute(
        "SELECT count(*) FROM alert_outbox WHERE status = 'pending'"
    ).fetchone()[0]
