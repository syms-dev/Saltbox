from __future__ import annotations

import json
import os
import time
from pathlib import Path

from saltbox_ui.state.system import (
    backup_summary,
    container_stats,
    host_stats,
    parse_size,
    tailscale_status,
)


def test_parse_size() -> None:
    assert parse_size("120.5MiB") == int(120.5 * 1024**2)
    assert parse_size("1.5GB") == 1_500_000_000
    assert parse_size("512B") == 512
    assert parse_size("--") == 0


def test_container_stats_busiest_first() -> None:
    lines = [
        {
            "Name": "plex",
            "CPUPerc": "12.50%",
            "MemUsage": "1.2GiB / 15.5GiB",
            "MemPerc": "7.7%",
            "PIDs": "80",
        },
        {
            "Name": "sonarr",
            "CPUPerc": "0.40%",
            "MemUsage": "250MiB / 15.5GiB",
            "MemPerc": "1.6%",
            "PIDs": "30",
        },
    ]
    stats = container_stats(lambda args: (0, "\n".join(json.dumps(x) for x in reversed(lines))))
    assert [s["name"] for s in stats] == ["plex", "sonarr"]
    assert stats[0]["cpu_percent"] == 12.5 and stats[0]["memory"] == int(1.2 * 1024**3)
    assert stats[1]["pids"] == 30


def test_host_stats_from_proc(tmp_path: Path) -> None:
    (tmp_path / "loadavg").write_text("2.00 1.50 1.00 1/200 1234\n")
    (tmp_path / "meminfo").write_text(
        "MemTotal: 16000000 kB\nMemAvailable: 4000000 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n"
    )
    (tmp_path / "uptime").write_text("3600.5 100.0\n")
    stats = host_stats(tmp_path)
    assert stats["load"] == [2.0, 1.5, 1.0]
    assert stats["memory_percent"] == 75.0
    assert stats["uptime"] == 3600
    assert stats["load_percent"] == round(min(100.0, 2.0 / (os.cpu_count() or 1) * 100), 1)


def test_tailscale_status() -> None:
    status = {
        "BackendState": "Running",
        "Version": "1.90.0",
        "Self": {
            "HostName": "saltbox",
            "DNSName": "saltbox.tail1234.ts.net.",
            "TailscaleIPs": ["100.64.0.5", "fd7a::5"],
            "Online": True,
            "UserID": 42,
        },
        "User": {"42": {"LoginName": "owner@example.com"}},
        "Peer": {"a": {"Online": True}, "b": {"Online": False}},
        "CurrentTailnet": {"MagicDNSEnabled": True},
    }
    info = tailscale_status(lambda args: (0, json.dumps(status)))
    assert info["running"] and info["dns_name"] == "saltbox.tail1234.ts.net"
    assert info["owner"] == "owner@example.com"
    assert (info["peers"], info["peers_online"]) == (2, 1)
    assert tailscale_status(lambda args: (127, "not installed")) == {"installed": False}
    stopped = tailscale_status(lambda args: (1, "failed to connect to local tailscaled"))
    assert stopped["running"] is False and "tailscaled" in stopped["error"]


def test_backup_summary(tmp_path: Path) -> None:
    backups = tmp_path / "seed" / "Backups"
    (backups / "old").mkdir(parents=True)
    old = backups / "old" / "opt.tar"
    old.write_bytes(b"x" * 10)
    os.utime(old, (time.time() - 86400, time.time() - 86400))
    (backups / "opt.tar").write_bytes(b"x" * 20)
    config = {
        "backup": {
            "cron": {"cron_time": "weekly"},
            "local": {"enable": True, "destination": str(tmp_path / "{{ user.name }}" / "Backups")},
            "rclone": {"enable": False, "destination": "google:/Backups"},
        }
    }
    summary = backup_summary(config, "seed")
    assert summary["schedule"] == "weekly"
    assert summary["destinations"][0] == {
        "kind": "local",
        "enabled": True,
        "destination": str(backups),
    }
    assert summary["latest"]["path"].endswith("Backups/opt.tar") and summary["latest"]["size"] == 20
    assert backup_summary({}, "seed")["configured"] is False
