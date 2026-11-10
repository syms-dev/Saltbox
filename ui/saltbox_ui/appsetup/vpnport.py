"""Keep qBittorrent listening on the port the VPN forwards to it.

With qBittorrent inside Gluetun (``qbittorrent_docker_network_mode:
"container:gluetun"``) and ``gluetun_vpn_port_forwarding: "on"``, ProtonVPN
forwards one port to the tunnel and changes it whenever the VPN reconnects.
Gluetun writes the current port to a file and its log; qBittorrent has to
listen on that port for peers to reach it.

Gluetun's own hook for this (``VPN_PORT_FORWARDING_UP_COMMAND``) takes a
``{{PORTS}}`` placeholder that Ansible's templating would try to fill in, so
the sync runs from here instead: a setup task applies it once, and a systemd
timer re-runs ``sbx setup sync-port`` every few minutes.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

STATUS_FILE = "/tmp/gluetun/forwarded_port"  # Gluetun's default VPN_PORT_FORWARDING_STATUS_FILE
PORT_LOG_RE = re.compile(r"port forwarded is (\d+)", re.I)
UNIT = "saltbox-ui-portsync"
INTERVAL = "5min"

ContainerReader = Callable[[str, str], str]
Systemctl = Callable[..., tuple[int, str]]


def docker_cat(container: str, path: str) -> str:
    """A file's contents from inside a running container, or ''."""
    if shutil.which("docker") is None:
        return ""
    try:
        result = subprocess.run(
            ["docker", "exec", container, "cat", path],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def forwarded_port(
    gluetun: str, read_file: ContainerReader, read_log: Callable[[str], str] | None
) -> int | None:
    """The port Gluetun currently forwards: its status file first, then its log."""
    text = read_file(gluetun, STATUS_FILE).strip()
    if text.isdigit() and 0 < int(text) < 65536:
        return int(text)
    if read_log is not None:
        found = PORT_LOG_RE.findall(read_log(gluetun))
        if found:
            return int(found[-1])
    return None


def sbx_command() -> str:
    found = shutil.which("sbx")
    return found if found else f"{sys.executable} -m saltbox_ui.cli"


def unit_files(command: str | None = None) -> dict[str, str]:
    command = command or sbx_command()
    return {
        f"{UNIT}.service": f"""[Unit]
Description=Saltbox UI: point qBittorrent at the VPN's forwarded port
After=docker.service

[Service]
Type=oneshot
ExecStart={command} setup sync-port
""",
        f"{UNIT}.timer": f"""[Unit]
Description=Saltbox UI: check the VPN's forwarded port every {INTERVAL}

[Timer]
OnBootSec=2min
OnUnitActiveSec={INTERVAL}
Unit={UNIT}.service

[Install]
WantedBy=timers.target
""",
    }


def default_systemctl(*args: str) -> tuple[int, str]:
    if shutil.which("systemctl") is None:
        return 127, "systemctl not found"
    result = subprocess.run(
        ["systemctl", *args], capture_output=True, text=True, check=False, timeout=60
    )
    return result.returncode, (result.stdout + result.stderr).strip()


def timer_installed(unit_dir: Path, systemctl: Systemctl) -> bool:
    if not all((unit_dir / name).exists() for name in unit_files()):
        return False
    code, _ = systemctl("is-enabled", f"{UNIT}.timer")
    return code == 0


def install_timer(unit_dir: Path, systemctl: Systemctl) -> None:
    unit_dir.mkdir(parents=True, exist_ok=True)
    for name, text in unit_files().items():
        (unit_dir / name).write_text(text, encoding="utf-8")
    systemctl("daemon-reload")
    code, output = systemctl("enable", "--now", f"{UNIT}.timer")
    if code != 0:
        raise RuntimeError(output or f"systemctl exited {code}")
