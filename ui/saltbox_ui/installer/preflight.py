"""Preflight checks for a fresh install.

The same checks ``sb setup`` performs (Ubuntu release, architecture, LXC,
desktop environment, disk space) plus the warnings the docs give about
servers that break the install: Docker or a web server preinstalled, ports
80 and 443 in use, and not enough memory or disk.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..layout import Layout

SETUP_RELEASES = ("24.04", "26.04")
RUNTIME_RELEASES = ("22.04", "24.04", "26.04")
MIN_FREE_BYTES = 2 * 1024**3
RECOMMENDED_DISK_BYTES = 100 * 1024**3
RECOMMENDED_MEMORY_BYTES = 4 * 1024**3


@dataclass
class Check:
    id: str
    title: str
    status: str  # "pass", "warn", "fail", "skip"
    detail: str = ""
    hint: str = ""

    @property
    def blocking(self) -> bool:
        return self.status == "fail"

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "hint": self.hint,
        }


@dataclass
class Probe:
    """Everything the checks read from the host, replaceable in tests."""

    os_release: dict[str, str] = field(default_factory=dict)
    euid: int = 0
    machine: str = "x86_64"
    virt: str = "none"
    desktop_installed: bool = False
    docker_present: bool = False
    listening_ports: set[int] = field(default_factory=set)
    memory_bytes: int = 0
    disks: dict[str, tuple[int, int]] = field(default_factory=dict)  # path -> (total, free)
    sb_version: str | None = None
    repo_ok: bool = False
    configs_present: bool = False
    existing_install: bool = False
    internet: bool = True

    @classmethod
    def from_host(cls, layout: Layout) -> Probe:
        return cls(
            os_release=read_os_release(),
            euid=os.geteuid(),
            machine=os.uname().machine,
            virt=detect_virt(),
            desktop_installed=package_installed("ubuntu-desktop"),
            docker_present=shutil.which("docker") is not None
            or Path("/var/run/docker.sock").exists(),
            listening_ports=listening_tcp_ports(),
            memory_bytes=total_memory(),
            disks={
                p: disk_totals(p)
                for p in ("/", str(layout.appdata), "/mnt/local")
                if Path(p).exists()
            },
            sb_version=sb_version(layout.sb_binary),
            repo_ok=layout.playbook.exists() and layout.schema_dir.exists(),
            configs_present=layout.config_file("accounts").exists(),
            existing_install=layout.facts_dir.exists() or (layout.appdata / "traefik").exists(),
            internet=can_reach("github.com", 443),
        )


def run_preflight(layout: Layout, probe: Probe | None = None) -> list[Check]:
    p = probe or Probe.from_host(layout)
    checks: list[Check] = []

    checks.append(
        Check(
            "root",
            "Running as root",
            "pass" if p.euid == 0 else "fail",
            "" if p.euid == 0 else "the installer must run as root",
            "" if p.euid == 0 else "start it with sudo",
        )
    )

    release = p.os_release.get("VERSION_ID", "")
    distro = p.os_release.get("ID", "")
    if distro != "ubuntu":
        checks.append(
            Check(
                "os",
                "Ubuntu Server",
                "fail",
                f"detected {distro or 'unknown'}",
                "Saltbox supports Ubuntu Server only",
            )
        )
    elif release in SETUP_RELEASES:
        checks.append(Check("os", "Ubuntu Server", "pass", f"Ubuntu {release}"))
    elif release in RUNTIME_RELEASES:
        checks.append(
            Check(
                "os",
                "Ubuntu Server",
                "warn",
                f"Ubuntu {release}",
                f"fresh installs are supported on {', '.join(SETUP_RELEASES)}; "
                "existing 22.04 installs keep working",
            )
        )
    else:
        checks.append(
            Check(
                "os",
                "Ubuntu Server",
                "fail",
                f"Ubuntu {release or 'unknown'}",
                f"install Ubuntu Server {' or '.join(SETUP_RELEASES)}",
            )
        )

    checks.append(
        Check(
            "arch",
            "x86_64 CPU",
            "pass" if p.machine.endswith("x86_64") else "fail",
            p.machine,
            "" if p.machine.endswith("x86_64") else "ARM and other architectures are not supported",
        )
    )
    checks.append(
        Check(
            "lxc",
            "Not an LXC container",
            "fail" if p.virt == "lxc" else "pass",
            p.virt if p.virt != "none" else "bare metal or a full VM",
            "LXC containers are not supported" if p.virt == "lxc" else "",
        )
    )
    checks.append(
        Check(
            "desktop",
            "No desktop environment",
            "fail" if p.desktop_installed else "pass",
            "ubuntu-desktop is installed" if p.desktop_installed else "",
            "Only Ubuntu Server is supported" if p.desktop_installed else "",
        )
    )
    checks.append(
        Check(
            "docker",
            "Docker not preinstalled",
            "warn" if p.docker_present else "pass",
            "a Docker install was found" if p.docker_present else "",
            "the docs ask for a fresh server; a preinstalled Docker often breaks the install"
            if p.docker_present
            else "",
        )
    )
    busy = sorted(port for port in (80, 443) if port in p.listening_ports)
    checks.append(
        Check(
            "ports",
            "Ports 80 and 443 free",
            "warn" if busy else "pass",
            f"something is listening on {', '.join(map(str, busy))}" if busy else "",
            "stop or remove the web server before installing; Traefik needs both ports"
            if busy
            else "",
        )
    )

    if p.memory_bytes:
        ok = p.memory_bytes >= RECOMMENDED_MEMORY_BYTES
        checks.append(
            Check(
                "memory",
                "Memory",
                "pass" if ok else "warn",
                _fmt(p.memory_bytes),
                "" if ok else "4 GiB or more is recommended",
            )
        )

    for path, (total, free) in p.disks.items():
        if free < MIN_FREE_BYTES:
            checks.append(
                Check(
                    f"disk:{path}",
                    f"Disk space on {path}",
                    "fail",
                    f"{_fmt(free)} free of {_fmt(total)}",
                    "sb refuses to run with less than 2 GiB free",
                )
            )
        elif total < RECOMMENDED_DISK_BYTES and path == "/":
            checks.append(
                Check(
                    f"disk:{path}",
                    f"Disk space on {path}",
                    "warn",
                    f"{_fmt(free)} free of {_fmt(total)}",
                    "100 GB is the minimum the docs suggest; 500 GB is realistic",
                )
            )
        else:
            checks.append(
                Check(
                    f"disk:{path}",
                    f"Disk space on {path}",
                    "pass",
                    f"{_fmt(free)} free of {_fmt(total)}",
                )
            )

    checks.append(
        Check(
            "sb",
            "sb CLI installed",
            "pass" if p.sb_version else "fail",
            p.sb_version or "not found",
            ""
            if p.sb_version
            else "run the bootstrap: curl -sL https://install.saltbox.dev | sudo -H bash",
        )
    )
    checks.append(
        Check(
            "repo",
            "Saltbox repository present",
            "pass" if p.repo_ok else "fail",
            str(layout.repo),
            "" if p.repo_ok else "the bootstrap clones it to /srv/git/saltbox",
        )
    )
    checks.append(
        Check(
            "configs",
            "Configuration files present",
            "pass" if p.configs_present else "warn",
            "" if p.configs_present else "accounts.yml is missing",
            "" if p.configs_present else "the installer will create them from the defaults",
        )
    )
    checks.append(
        Check(
            "existing",
            "Fresh server",
            "warn" if p.existing_install else "pass",
            "an earlier Saltbox install was found" if p.existing_install else "",
            "re-running the install is safe; existing app configs are kept"
            if p.existing_install
            else "",
        )
    )
    checks.append(
        Check(
            "internet",
            "Internet access",
            "pass" if p.internet else "fail",
            "" if p.internet else "cannot reach github.com",
            "" if p.internet else "the install downloads packages and images",
        )
    )
    return checks


def summarize(checks: list[Check]) -> dict[str, int]:
    counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    for check in checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    return counts


# -- host probes ------------------------------------------------------------
def read_os_release(path: str = "/etc/os-release") -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                result[key] = value.strip().strip('"')
    except OSError:
        pass
    return result


def _run(args: list[str], timeout: int = 5) -> tuple[int, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""
    return result.returncode, (result.stdout + result.stderr).strip()


def detect_virt() -> str:
    if shutil.which("systemd-detect-virt") is None:
        return "none"
    _code, output = _run(["systemd-detect-virt", "-c"])
    return output.lower() if output else "none"


def package_installed(name: str) -> bool:
    if shutil.which("dpkg") is None:
        return False
    code, _ = _run(["dpkg", "-s", name])
    return code == 0


def listening_tcp_ports() -> set[int]:
    ports: set[int] = set()
    if shutil.which("ss") is None:
        return ports
    _, output = _run(["ss", "-Hltn"])
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 4 and ":" in parts[3]:
            port = parts[3].rsplit(":", 1)[-1]
            if port.isdigit():
                ports.add(int(port))
    return ports


def total_memory() -> int:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def disk_totals(path: str) -> tuple[int, int]:
    usage = shutil.disk_usage(path)
    return usage.total, usage.free


def sb_version(binary: Path) -> str | None:
    if not Path(binary).exists():
        return None
    code, output = _run([str(binary), "version"], timeout=20)
    if code != 0:
        return "installed"
    return output.splitlines()[0] if output else "installed"


def can_reach(host: str, port: int, timeout: float = 3.0) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _fmt(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TiB"


ProbeFactory = Callable[[Layout], Probe]
