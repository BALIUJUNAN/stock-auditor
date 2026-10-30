"""按序号执行 ``migrations/`` 下的 SQL 文件。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import duckdb

from stock_auditor import paths

MIGRATIONS_DIR = paths.project_root() / "migrations"
MIGRATION_FILENAME_PATTERN = re.compile(r"^(?P<version>\d{4})_(?P<name>.+)\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path


def discover_migrations(directory: Path | None = None) -> list[Migration]:
    """按版本号升序返回迁移文件；文件名必须形如 ``0001_init.sql``。"""
    root = Path(directory) if directory is not None else MIGRATIONS_DIR
    if not root.exists():
        return []
    migrations: list[Migration] = []
    for path in root.glob("*.sql"):
        match = MIGRATION_FILENAME_PATTERN.match(path.name)
        if match is None:
            raise ValueError(f"迁移文件名不符合 NNNN_名称.sql：{path.name}")
        migrations.append(
            Migration(
                version=int(match.group("version")),
                name=match.group("name"),
                path=path,
            )
        )
    migrations.sort(key=lambda migration: migration.version)
    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        raise ValueError(f"迁移版本号重复：{versions}")
    return migrations


def _ensure_version_table(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL,
            applied_at TIMESTAMP NOT NULL DEFAULT current_timestamp
        )
        """
    )


def _applied_versions(connection: duckdb.DuckDBPyConnection) -> set[int]:
    rows = connection.execute("SELECT version FROM schema_version").fetchall()
    return {int(row[0]) for row in rows}


def apply_migrations(
    connection: duckdb.DuckDBPyConnection,
    directory: Path | None = None,
) -> list[int]:
    """应用尚未执行的迁移，返回本次应用的版本号列表。已应用则跳过。"""
    _ensure_version_table(connection)
    applied = _applied_versions(connection)
    newly_applied: list[int] = []
    for migration in discover_migrations(directory):
        if migration.version in applied:
            continue
        sql = migration.path.read_text(encoding="utf-8")
        connection.execute("BEGIN")
        try:
            connection.execute(sql)
            connection.execute(
                "INSERT INTO schema_version (version, name) VALUES (?, ?)",
                [migration.version, migration.name],
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        newly_applied.append(migration.version)
    return newly_applied
