"""Start the client automatically when the user logs in (`cloudsync install-service`).

Per-user only: nothing here needs administrator rights. `service_plan` is a pure function that
says what to write and run for a platform, so it can be checked (and shown with `--print`)
without touching the machine.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

NAME = "cloudsync"
TASK = "CloudSync backup"
LAUNCHD_LABEL = "com.personalcloud.cloudsync"


@dataclass
class ServicePlan:
    description: str
    files: dict[Path, str] = field(default_factory=dict)
    install_commands: list[list[str]] = field(default_factory=list)
    uninstall_commands: list[list[str]] = field(default_factory=list)
    uninstall_files: list[Path] = field(default_factory=list)


def _argv(python: str, config_dir: Path | None, frozen: bool = False) -> list[str]:
    # A packaged .exe is the program itself; from source it is `python -m cloudsync.main`.
    args = [python] if frozen else [python, "-m", "cloudsync.main"]
    if config_dir is not None:
        args += ["--config-dir", str(config_dir)]
    return args + ["run"]


def _quote(arg: str) -> str:
    return f'"{arg}"' if " " in arg else arg


def service_plan(
    platform: str,
    python: str,
    home: Path,
    config_dir: Path | None = None,
    frozen: bool = False,
) -> ServicePlan:
    argv = _argv(python, config_dir, frozen)

    if platform.startswith("linux"):
        unit = home / ".config" / "systemd" / "user" / f"{NAME}.service"
        text = (
            "[Unit]\n"
            "Description=Personal Cloud backup client\n"
            "After=network-online.target\n"
            "Wants=network-online.target\n\n"
            "[Service]\n"
            f"ExecStart={' '.join(_quote(a) for a in argv)}\n"
            "Restart=on-failure\n"
            "RestartSec=30\n"
            "RestartPreventExitStatus=3\n"
            "Nice=10\n"
            "IOSchedulingClass=idle\n"
            "CPUSchedulingPolicy=idle\n\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )
        return ServicePlan(
            "a systemd user service",
            files={unit: text},
            install_commands=[
                ["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "--now", NAME],
            ],
            uninstall_commands=[["systemctl", "--user", "disable", "--now", NAME]],
            uninstall_files=[unit],
        )

    if platform == "darwin":
        plist = home / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
        items = "".join(f"    <string>{a}</string>\n" for a in argv)
        text = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            f"  <key>Label</key><string>{LAUNCHD_LABEL}</string>\n"
            f"  <key>ProgramArguments</key><array>\n{items}  </array>\n"
            "  <key>RunAtLoad</key><true/>\n"
            "  <key>KeepAlive</key><true/>\n"
            "  <key>ProcessType</key><string>Background</string>\n"
            "  <key>LowPriorityIO</key><true/>\n"
            "  <key>Nice</key><integer>10</integer>\n"
            "</dict></plist>\n"
        )
        return ServicePlan(
            "a launchd agent",
            files={plist: text},
            install_commands=[["launchctl", "load", "-w", str(plist)]],
            uninstall_commands=[["launchctl", "unload", "-w", str(plist)]],
            uninstall_files=[plist],
        )

    if platform == "win32":
        if frozen:
            # The packaged .exe is a console program: start it hidden so no window sits open.
            inner = " ".join(f"'{a}'" for a in argv)
            command = f'powershell.exe -NoProfile -WindowStyle Hidden -Command "& {inner}"'
        else:
            # pythonw.exe has no console window, so nothing flashes up at logon.
            windowless = Path(python).with_name("pythonw.exe")
            exe = str(windowless) if windowless.exists() else python
            command = " ".join(_quote(a) for a in [exe, *argv[1:]])
        return ServicePlan(
            "a Task Scheduler task that runs at logon",
            install_commands=[
                ["schtasks", "/Create", "/TN", TASK, "/SC", "ONLOGON", "/TR", command, "/F"],
                ["schtasks", "/Run", "/TN", TASK],
            ],
            uninstall_commands=[
                ["schtasks", "/End", "/TN", TASK],
                ["schtasks", "/Delete", "/TN", TASK, "/F"],
            ],
        )

    raise RuntimeError(f"automatic start is not supported on {platform}")


def install(plan: ServicePlan) -> list[str]:
    """Write the files and run the commands; returns the commands that failed."""
    for path, text in plan.files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return _run(plan.install_commands)


def uninstall(plan: ServicePlan) -> list[str]:
    failed = _run(plan.uninstall_commands)
    for path in plan.uninstall_files:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return failed


def _run(commands: list[list[str]]) -> list[str]:
    failed = []
    for command in commands:
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True)
        except OSError as exc:
            failed.append(f"{' '.join(command)}: {exc}")
            continue
        if result.returncode != 0:
            failed.append(f"{' '.join(command)}: {(result.stderr or result.stdout).strip()}")
    return failed


def current_platform() -> str:
    return sys.platform


def home_dir() -> Path:
    return Path(os.path.expanduser("~"))
