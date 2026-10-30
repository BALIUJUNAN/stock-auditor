"""T3.5：Windows/macOS/Linux 开机自启安装与卸载。"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from stock_auditor.autostart import (
    AutostartError,
    AutostartResult,
    install_autostart,
    uninstall_autostart,
)


class FakeRegistry:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set_value(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete_value(self, name: str) -> bool:
        return self.values.pop(name, None) is not None


class FakeRunner:
    def __init__(self, codes: dict[str, int] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.codes = codes or {}

    def __call__(self, command: Sequence[str]) -> int:
        self.calls.append(list(command))
        return self.codes.get(command[0], 0)


def test_windows_install_and_uninstall() -> None:
    registry = FakeRegistry()
    result = install_autostart(
        platform_name="win32",
        registry=registry,
        python="C:/Python/python.exe",
    )
    assert isinstance(result, AutostartResult)
    assert result.target.startswith("HKCU\\Software\\Microsoft\\Windows")
    value = registry.values["StockAuditor"]
    assert "C:/Python/python.exe" in value
    assert "-m stock_auditor serve" in value

    removed = uninstall_autostart(platform_name="win32", registry=registry)
    assert removed.changed is True
    assert registry.values == {}

    again = uninstall_autostart(platform_name="win32", registry=registry)
    assert again.changed is False


def test_linux_systemd_install_and_uninstall(tmp_path: Path) -> None:
    runner = FakeRunner()
    project = tmp_path / "project"
    result = install_autostart(
        platform_name="linux",
        runner=runner,
        home=tmp_path / "home",
        python="/usr/bin/python3",
        project_root=project,
    )
    unit = tmp_path / "home" / ".config" / "systemd" / "user" / "stock-auditor.service"
    assert result.target == str(unit)
    text = unit.read_text(encoding="utf-8")
    assert "ExecStart=/usr/bin/python3 -m stock_auditor serve" in text
    assert f"WorkingDirectory={project}" in text
    assert "WantedBy=default.target" in text
    assert runner.calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "stock-auditor.service"],
    ]

    removed = uninstall_autostart(
        platform_name="linux",
        runner=runner,
        home=tmp_path / "home",
    )
    assert removed.changed is True
    assert not unit.exists()
    assert ["systemctl", "--user", "disable", "--now", "stock-auditor.service"] in runner.calls
    assert runner.calls[-1] == ["systemctl", "--user", "daemon-reload"]


def test_macos_launch_agent_install_and_uninstall(tmp_path: Path) -> None:
    runner = FakeRunner()
    result = install_autostart(
        platform_name="darwin",
        runner=runner,
        home=tmp_path / "home",
        python="/usr/local/bin/python3",
        project_root=tmp_path / "project",
    )
    plist = (
        tmp_path
        / "home"
        / "Library"
        / "LaunchAgents"
        / "com.stockauditor.serve.plist"
    )
    assert result.target == str(plist)
    text = plist.read_text(encoding="utf-8")
    assert "<string>com.stockauditor.serve</string>" in text
    assert "<string>/usr/local/bin/python3</string>" in text
    assert "<string>-m</string>" in text
    assert "<string>stock_auditor</string>" in text
    assert runner.calls[0][0] == "launchctl"
    assert runner.calls[1] == ["launchctl", "load", str(plist)]

    removed = uninstall_autostart(
        platform_name="darwin",
        runner=runner,
        home=tmp_path / "home",
    )
    assert removed.changed is True
    assert not plist.exists()

    again = uninstall_autostart(
        platform_name="darwin",
        runner=runner,
        home=tmp_path / "home",
    )
    assert again.changed is False


def test_linux_failure_raises(tmp_path: Path) -> None:
    runner = FakeRunner({"systemctl": 1})
    with pytest.raises(AutostartError):
        install_autostart(
            platform_name="linux",
            runner=runner,
            home=tmp_path / "home",
            python="/usr/bin/python3",
            project_root=tmp_path / "project",
        )


def test_unsupported_platform() -> None:
    with pytest.raises(AutostartError):
        install_autostart(platform_name="freebsd")
    with pytest.raises(AutostartError):
        uninstall_autostart(platform_name="freebsd")
