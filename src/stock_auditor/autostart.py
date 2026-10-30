"""开机自启：Windows 注册表、macOS launchd、Linux systemd user。"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from xml.sax.saxutils import escape

WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WINDOWS_VALUE_NAME = "StockAuditor"
MACOS_LABEL = "com.stockauditor.serve"
LINUX_UNIT_NAME = "stock-auditor.service"

Runner = Callable[[Sequence[str]], int]


class AutostartError(RuntimeError):
    """自启动配置失败。"""


@dataclass(frozen=True)
class AutostartResult:
    platform: str
    target: str
    command: tuple[str, ...]
    changed: bool


class Registry(Protocol):
    def set_value(self, name: str, value: str) -> None: ...

    def delete_value(self, name: str) -> bool: ...


class _WindowsRegistry:
    def set_value(self, name: str, value: str) -> None:
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            WINDOWS_RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete_value(self, name: str) -> bool:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                WINDOWS_RUN_KEY,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            return False
        return True


def serve_command(*, python: str | Path | None = None) -> tuple[str, ...]:
    """返回 ``sa serve`` 的等效启动命令。"""
    executable = str(python) if python is not None else sys.executable
    return (executable, "-m", "stock_auditor", "serve")


def _run(command: Sequence[str]) -> int:
    completed = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode


def _require_success(command: Sequence[str], runner: Runner) -> None:
    code = runner(command)
    if code != 0:
        raise AutostartError(f"命令失败（退出码 {code}）：{' '.join(command)}")


def _windows_install(
    command: Sequence[str],
    registry: Registry,
) -> AutostartResult:
    line = subprocess.list2cmdline(list(command))
    registry.set_value(WINDOWS_VALUE_NAME, line)
    return AutostartResult(
        platform="win32",
        target=f"HKCU\\{WINDOWS_RUN_KEY}\\{WINDOWS_VALUE_NAME}",
        command=tuple(command),
        changed=True,
    )


def _windows_uninstall(registry: Registry) -> AutostartResult:
    removed = registry.delete_value(WINDOWS_VALUE_NAME)
    return AutostartResult(
        platform="win32",
        target=f"HKCU\\{WINDOWS_RUN_KEY}\\{WINDOWS_VALUE_NAME}",
        command=(),
        changed=removed,
    )


def _plist_path(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{MACOS_LABEL}.plist"


def _install_macos(
    command: Sequence[str],
    *,
    home: Path,
    project_root: Path,
    runner: Runner,
) -> AutostartResult:
    path = _plist_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    log_path = project_root / "var" / "logs" / "autostart.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    arguments = "\n".join(
        f"        <string>{escape(item)}</string>" for item in command
    )
    path.write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" "
        "\"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
        "<plist version=\"1.0\">\n"
        "<dict>\n"
        "    <key>Label</key>\n"
        f"    <string>{MACOS_LABEL}</string>\n"
        "    <key>ProgramArguments</key>\n"
        "    <array>\n"
        f"{arguments}\n"
        "    </array>\n"
        "    <key>WorkingDirectory</key>\n"
        f"    <string>{escape(str(project_root))}</string>\n"
        "    <key>RunAtLoad</key>\n"
        "    <true/>\n"
        "    <key>KeepAlive</key>\n"
        "    <true/>\n"
        "    <key>StandardOutPath</key>\n"
        f"    <string>{escape(str(log_path))}</string>\n"
        "    <key>StandardErrorPath</key>\n"
        f"    <string>{escape(str(log_path))}</string>\n"
        "</dict>\n"
        "</plist>\n",
        encoding="utf-8",
    )
    runner(["launchctl", "unload", str(path)])
    _require_success(["launchctl", "load", str(path)], runner)
    return AutostartResult(
        platform="darwin",
        target=str(path),
        command=tuple(command),
        changed=True,
    )


def _uninstall_macos(*, home: Path, runner: Runner) -> AutostartResult:
    path = _plist_path(home)
    if not path.exists():
        return AutostartResult(
            platform="darwin",
            target=str(path),
            command=(),
            changed=False,
        )
    runner(["launchctl", "unload", str(path)])
    path.unlink()
    return AutostartResult(
        platform="darwin",
        target=str(path),
        command=(),
        changed=True,
    )


def _unit_path(home: Path) -> Path:
    return home / ".config" / "systemd" / "user" / LINUX_UNIT_NAME


def _systemd_quote(part: str) -> str:
    if not part or any(char.isspace() or char in "\"'" for char in part):
        return '"' + part.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return part


def _install_linux(
    command: Sequence[str],
    *,
    home: Path,
    project_root: Path,
    runner: Runner,
) -> AutostartResult:
    path = _unit_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    exec_start = " ".join(_systemd_quote(item) for item in command)
    path.write_text(
        "[Unit]\n"
        "Description=Stock Auditor serve\n"
        "After=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={_systemd_quote(str(project_root))}\n"
        f"ExecStart={exec_start}\n"
        "Restart=on-failure\n"
        "RestartSec=10\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n",
        encoding="utf-8",
    )
    _require_success(["systemctl", "--user", "daemon-reload"], runner)
    _require_success(
        ["systemctl", "--user", "enable", "--now", LINUX_UNIT_NAME],
        runner,
    )
    return AutostartResult(
        platform="linux",
        target=str(path),
        command=tuple(command),
        changed=True,
    )


def _uninstall_linux(*, home: Path, runner: Runner) -> AutostartResult:
    path = _unit_path(home)
    if not path.exists():
        return AutostartResult(
            platform="linux",
            target=str(path),
            command=(),
            changed=False,
        )
    runner(["systemctl", "--user", "disable", "--now", LINUX_UNIT_NAME])
    path.unlink()
    runner(["systemctl", "--user", "daemon-reload"])
    return AutostartResult(
        platform="linux",
        target=str(path),
        command=(),
        changed=True,
    )


def install_autostart(
    *,
    platform_name: str | None = None,
    runner: Runner | None = None,
    registry: Registry | None = None,
    home: Path | None = None,
    python: str | Path | None = None,
    project_root: Path | None = None,
) -> AutostartResult:
    """安装开机自启；测试可注入 ``runner`` / ``registry`` / ``home``。"""
    system = platform_name or sys.platform
    execute = runner or _run
    root = Path(project_root) if project_root is not None else Path.cwd()
    command = serve_command(python=python)
    if system == "win32":
        return _windows_install(command, registry or _WindowsRegistry())
    if system == "darwin":
        return _install_macos(
            command,
            home=Path(home) if home is not None else Path.home(),
            project_root=root,
            runner=execute,
        )
    if system.startswith("linux"):
        return _install_linux(
            command,
            home=Path(home) if home is not None else Path.home(),
            project_root=root,
            runner=execute,
        )
    raise AutostartError(f"不支持的系统：{system}")


def uninstall_autostart(
    *,
    platform_name: str | None = None,
    runner: Runner | None = None,
    registry: Registry | None = None,
    home: Path | None = None,
) -> AutostartResult:
    """移除开机自启；重复卸载返回 ``changed=False``。"""
    system = platform_name or sys.platform
    execute = runner or _run
    if system == "win32":
        return _windows_uninstall(registry or _WindowsRegistry())
    if system == "darwin":
        return _uninstall_macos(
            home=Path(home) if home is not None else Path.home(),
            runner=execute,
        )
    if system.startswith("linux"):
        return _uninstall_linux(
            home=Path(home) if home is not None else Path.home(),
            runner=execute,
        )
    raise AutostartError(f"不支持的系统：{system}")
