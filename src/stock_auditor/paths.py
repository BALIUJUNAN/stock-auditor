"""项目路径解析。

代码与配置以项目根目录为基准；运行数据默认放项目根下的 ``var/``，
可用环境变量 ``SA_HOME`` 改到其他位置。所有路径均使用 pathlib。
"""

from __future__ import annotations

import os
from pathlib import Path

# src/stock_auditor/paths.py -> 项目根目录
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

DATA_DIR_NAMES: tuple[str, ...] = ("db", "logs", "cache", "reports", "locks", "state")


def project_root() -> Path:
    """返回项目根目录。"""
    return PROJECT_ROOT


def config_dir() -> Path:
    """返回默认配置目录。"""
    return PROJECT_ROOT / "config"


def local_config_dir() -> Path:
    """返回客户私有配置目录（不进 Git）。"""
    return config_dir() / "local"


def data_root() -> Path:
    """返回运行数据根目录；``SA_HOME`` 优先于项目根下的 ``var/``。"""
    raw = os.environ.get("SA_HOME", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return PROJECT_ROOT / "var"


def data_dir(name: str) -> Path:
    """返回运行数据根目录下的指定子目录。"""
    return data_root() / name


def db_dir() -> Path:
    return data_dir("db")


def logs_dir() -> Path:
    return data_dir("logs")


def cache_dir() -> Path:
    return data_dir("cache")


def reports_dir() -> Path:
    return data_dir("reports")


def locks_dir() -> Path:
    return data_dir("locks")


def state_dir() -> Path:
    return data_dir("state")


def ensure_data_dirs() -> Path:
    """创建全部运行数据子目录，返回数据根目录。"""
    root = data_root()
    for name in DATA_DIR_NAMES:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root
