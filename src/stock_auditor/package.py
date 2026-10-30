"""交付打包：生成源码压缩包，并扫描密钥与私有数据。

打包白名单只包含运行所需源码、默认配置、迁移、文档与安装脚本；
``.env``、``config/local/`` 下的真实配置、``var/`` 运行数据与测试代码默认都不进包。
生成前会扫描待打包文本：

- 密钥：常见环境变量被写成真实值、``sk-`` API Key、飞书 Webhook、私钥块；
- 私有数据：``config/prompts/`` 出现 6 位股票代码或 7 只校准股名称。
"""

from __future__ import annotations

import hashlib
import os
import re
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from stock_auditor import __version__
from stock_auditor.paths import project_root as default_project_root

_INCLUDE_DIRS: tuple[str, ...] = ("src", "config", "migrations", "docs", "scripts")
_INCLUDE_ROOT_FILES: tuple[str, ...] = (
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    ".env.example",
    ".gitignore",
    "install.ps1",
    "install.sh",
)
_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".github",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".idea",
        ".vscode",
        "var",
        "dist",
        "build",
        "node_modules",
        ".claude",
        ".worktrees",
    }
)
_EXCLUDED_SUFFIXES = frozenset(
    {
        ".pyc",
        ".pyo",
        ".duckdb",
        ".wal",
        ".db",
        ".sqlite",
        ".parquet",
        ".zip",
        ".log",
        ".tmp",
        ".bak",
        ".orig",
        ".pdf",
        ".xlsx",
        ".xls",
        ".png",
        ".jpg",
        ".jpeg",
    }
)
# 内部探测记录与规划文档含真实行情样本或校准股标识，只留在工程仓库，不随交付包分发。
_INTERNAL_DOCS = frozenset(
    {"data_sources.md", "SPEC_RECONCILIATION.md", "OPEN_QUESTIONS.md"}
)

_SECRET_ENV_NAMES = (
    "LLM_API_KEY",
    "FEISHU_APP_SECRET",
    "FEISHU_WEBHOOK_SECRET",
    "TUSHARE_TOKEN",
    "COMMERCIAL_PASSWORD",
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?im)^[ \t]*(?:export[ \t]+)?"
    r"(?P<name>" + "|".join(_SECRET_ENV_NAMES) + r")"
    r"[ \t]*[:=][ \t]*(?P<value>[^\r\n]*)"
)
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")
_FEISHU_WEBHOOK = re.compile(
    r"https?://open\.feishu\.cn/open-apis/bot/v2/hook/[A-Za-z0-9_-]{8,}"
)
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
)
_A_SHARE_CODE = re.compile(r"(?<!\d)(?:00|30|60|68|8[34]|92|4[03])\d{4}(?!\d)")

_PLACEHOLDER_VALUES = frozenset(
    {
        "",
        "-",
        "none",
        "null",
        "secret",
        "token",
        "password",
        "changeme",
        "change-me",
        "app-secret",
        "test-secret",
        "fake-secret",
        "example-secret",
    }
)
_PLACEHOLDER_PREFIXES = (
    "your",
    "example",
    "placeholder",
    "changeme",
    "fake",
    "dummy",
    "test-",
    "<",
    "${",
    "{{",
    "$env:",
    "%",
)


class PackageError(RuntimeError):
    """打包前检查未通过。"""

    def __init__(self, problems: Sequence[PackageProblem]) -> None:
        self.problems = tuple(problems)
        lines = ["发现阻止打包的问题："]
        lines.extend(f"  {problem.describe()}" for problem in self.problems)
        super().__init__("\n".join(lines))


@dataclass(frozen=True)
class PackageProblem:
    """一条阻止打包的检查结果。"""

    path: str
    kind: str
    detail: str
    line: int | None = None

    def describe(self) -> str:
        location = self.path if self.line is None else f"{self.path}:{self.line}"
        return f"[{self.kind}] {location}：{self.detail}"


@dataclass(frozen=True)
class PackageResult:
    """打包成功结果。"""

    archive: Path
    files: tuple[str, ...]
    sha256: str
    size_bytes: int
    version: str = __version__


def _should_exclude(relative: Path) -> bool:
    parts = relative.parts
    if any(part in _EXCLUDED_DIRS for part in parts):
        return True
    name = relative.name
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    if relative.suffix.lower() in _EXCLUDED_SUFFIXES:
        return True
    if len(parts) >= 2 and parts[0] == "config" and parts[1] == "local":
        return not name.endswith(".example.yaml")
    return len(parts) >= 2 and parts[0] == "docs" and name in _INTERNAL_DOCS


def _candidate_files(root: Path, *, include_tests: bool) -> Iterator[Path]:
    directories = _INCLUDE_DIRS + (("tests",) if include_tests else ())
    for dirname in directories:
        base = root / dirname
        if base.is_dir():
            yield from (path for path in base.rglob("*") if path.is_file())
    for filename in _INCLUDE_ROOT_FILES:
        path = root / filename
        if path.is_file():
            yield path


def iter_package_files(root: Path, *, include_tests: bool = False) -> tuple[Path, ...]:
    """返回待打包文件（已排除私有配置、运行数据与缓存），按路径排序。"""
    selected = {
        path
        for path in _candidate_files(root, include_tests=include_tests)
        if not _should_exclude(path.relative_to(root))
    }
    return tuple(sorted(selected, key=lambda path: path.relative_to(root).as_posix()))


def _read_text(path: Path) -> str | None:
    data = path.read_bytes()
    if b"\x00" in data[:4096]:
        return None
    return data.decode("utf-8", errors="replace")


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _clean_value(raw: str) -> str:
    value = raw.strip()
    if value[:1] in {"'", '"'}:
        quote = value[0]
        end = value.find(quote, 1)
        if end != -1:
            value = value[1:end]
    else:
        value = value.split("#", 1)[0].strip()
    return value


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().strip("'\"").lower()
    if lowered in _PLACEHOLDER_VALUES:
        return True
    if lowered.startswith(_PLACEHOLDER_PREFIXES):
        return True
    return bool(lowered) and set(lowered) <= {"x", "*"}


def _scan_secrets(relative: str, text: str) -> list[PackageProblem]:
    problems: list[PackageProblem] = []
    for match in _SECRET_ASSIGNMENT.finditer(text):
        value = _clean_value(match.group("value"))
        if _is_placeholder(value):
            continue
        problems.append(
            PackageProblem(
                path=relative,
                kind="secret",
                detail=f"{match.group('name')} 疑似写入了真实值",
                line=_line_number(text, match.start()),
            )
        )
    for match in _OPENAI_KEY.finditer(text):
        problems.append(
            PackageProblem(
                path=relative,
                kind="secret",
                detail="疑似 OpenAI 风格 API Key（sk-…）",
                line=_line_number(text, match.start()),
            )
        )
    for match in _FEISHU_WEBHOOK.finditer(text):
        token = match.group(0).rsplit("/", 1)[-1]
        if _is_placeholder(token):
            continue
        problems.append(
            PackageProblem(
                path=relative,
                kind="secret",
                detail="疑似真实飞书 Webhook 地址",
                line=_line_number(text, match.start()),
            )
        )
    for match in _PRIVATE_KEY_BLOCK.finditer(text):
        problems.append(
            PackageProblem(
                path=relative,
                kind="secret",
                detail="包含私钥块",
                line=_line_number(text, match.start()),
            )
        )
    return problems


def _calibration_tokens() -> tuple[str, ...]:
    from stock_auditor.calibration import CALIBRATION_STOCKS

    tokens: list[str] = []
    for stock in CALIBRATION_STOCKS:
        tokens.extend((stock.code, stock.name))
    return tuple(tokens)


def _scan_prompts(relative: str, text: str) -> list[PackageProblem]:
    if not relative.startswith("config/prompts/"):
        return []
    problems: list[PackageProblem] = []
    for token in _calibration_tokens():
        offset = text.find(token)
        if offset == -1:
            continue
        problems.append(
            PackageProblem(
                path=relative,
                kind="private",
                detail=f"Prompt 中出现校准股标识：{token}",
                line=_line_number(text, offset),
            )
        )
    for match in _A_SHARE_CODE.finditer(text):
        problems.append(
            PackageProblem(
                path=relative,
                kind="private",
                detail=f"Prompt 中出现股票代码：{match.group(0)}",
                line=_line_number(text, match.start()),
            )
        )
    return problems


def scan_package_files(root: Path, files: Sequence[Path]) -> tuple[PackageProblem, ...]:
    """扫描待打包文本，返回全部密钥与私有数据问题。"""
    problems: list[PackageProblem] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        text = _read_text(path)
        if text is None:
            continue
        problems.extend(_scan_secrets(relative, text))
        problems.extend(_scan_prompts(relative, text))
    return tuple(problems)


def default_archive_path(root: Path) -> Path:
    """默认输出到 ``dist/stock-auditor-<版本>.zip``。"""
    return root / "dist" / f"stock-auditor-{__version__}.zip"


def _write_archive(archive: Path, root: Path, files: Sequence[Path]) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name(archive.name + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in files:
                relative = path.relative_to(root).as_posix()
                info = zipfile.ZipInfo(relative, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                mode = 0o755 if path.suffix == ".sh" else 0o644
                info.external_attr = (0o100000 | mode) << 16
                bundle.writestr(info, path.read_bytes())
        os.replace(temporary, archive)
    finally:
        if temporary.exists():
            temporary.unlink()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_package(
    project_root: Path | None = None,
    *,
    output: Path | None = None,
    include_tests: bool = False,
    force: bool = False,
) -> PackageResult:
    """生成交付压缩包；发现密钥或私有数据时抛出 :class:`PackageError`。"""
    root = Path(project_root) if project_root is not None else default_project_root()
    if not (root / "pyproject.toml").is_file():
        raise PackageError(
            [PackageProblem(path=str(root), kind="path", detail="项目根目录缺少 pyproject.toml")]
        )

    files = iter_package_files(root, include_tests=include_tests)
    if not files:
        raise PackageError(
            [PackageProblem(path=str(root), kind="path", detail="没有可打包的文件")]
        )

    problems = scan_package_files(root, files)
    if problems:
        raise PackageError(problems)

    archive = Path(output) if output is not None else default_archive_path(root)
    if not archive.is_absolute():
        archive = root / archive
    if archive.exists() and not force:
        raise PackageError(
            [
                PackageProblem(
                    path=str(archive),
                    kind="path",
                    detail="压缩包已存在；使用 --force 覆盖",
                )
            ]
        )

    _write_archive(archive, root, files)
    return PackageResult(
        archive=archive,
        files=tuple(path.relative_to(root).as_posix() for path in files),
        sha256=_sha256(archive),
        size_bytes=archive.stat().st_size,
    )
