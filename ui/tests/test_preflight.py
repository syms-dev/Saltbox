from __future__ import annotations

from pathlib import Path

from saltbox_ui.installer.preflight import (
    Check,
    Probe,
    read_os_release,
    run_preflight,
    summarize,
)
from saltbox_ui.layout import Layout

GIB = 1024**3


def good_probe(**overrides) -> Probe:
    base = {
        "os_release": {"ID": "ubuntu", "VERSION_ID": "24.04"},
        "euid": 0,
        "machine": "x86_64",
        "virt": "kvm",
        "memory_bytes": 8 * GIB,
        "disks": {"/": (500 * GIB, 400 * GIB)},
        "sb_version": "sb 1.2.3",
        "repo_ok": True,
        "configs_present": True,
        "existing_install": False,
        "internet": True,
    }
    base.update(overrides)
    return Probe(**base)


def by_id(checks: list[Check]) -> dict[str, Check]:
    return {c.id: c for c in checks}


def test_clean_host_passes(scratch_layout: Layout) -> None:
    checks = run_preflight(scratch_layout, good_probe())
    assert summarize(checks)["fail"] == 0
    assert summarize(checks)["warn"] == 0
    assert not any(c.blocking for c in checks)


def test_blocking_failures(scratch_layout: Layout) -> None:
    probe = good_probe(
        euid=1000,
        os_release={"ID": "debian", "VERSION_ID": "12"},
        machine="aarch64",
        virt="lxc",
        desktop_installed=True,
        disks={"/": (50 * GIB, 1 * GIB)},
        sb_version=None,
        repo_ok=False,
        internet=False,
    )
    checks = by_id(run_preflight(scratch_layout, probe))
    for check_id in ("root", "os", "arch", "lxc", "desktop", "disk:/", "sb", "repo", "internet"):
        assert checks[check_id].status == "fail", check_id
        assert checks[check_id].hint, check_id


def test_warnings_do_not_block(scratch_layout: Layout) -> None:
    probe = good_probe(
        os_release={"ID": "ubuntu", "VERSION_ID": "22.04"},
        docker_present=True,
        listening_ports={22, 80, 443},
        memory_bytes=2 * GIB,
        disks={"/": (60 * GIB, 30 * GIB)},
        configs_present=False,
        existing_install=True,
    )
    checks = by_id(run_preflight(scratch_layout, probe))
    for check_id in ("os", "docker", "ports", "memory", "disk:/", "configs", "existing"):
        assert checks[check_id].status == "warn", check_id
    assert "80, 443" in checks["ports"].detail
    assert summarize(run_preflight(scratch_layout, probe))["fail"] == 0


def test_unknown_ubuntu_release_fails(scratch_layout: Layout) -> None:
    probe = good_probe(os_release={"ID": "ubuntu", "VERSION_ID": "20.04"})
    assert by_id(run_preflight(scratch_layout, probe))["os"].status == "fail"


def test_small_data_disk_is_not_a_root_warning(scratch_layout: Layout) -> None:
    probe = good_probe(disks={"/": (500 * GIB, 400 * GIB), "/opt": (20 * GIB, 10 * GIB)})
    checks = by_id(run_preflight(scratch_layout, probe))
    assert checks["disk:/opt"].status == "pass"


def test_read_os_release(tmp_path: Path) -> None:
    path = tmp_path / "os-release"
    path.write_text('ID=ubuntu\nVERSION_ID="24.04"\nPRETTY_NAME="Ubuntu 24.04 LTS"\n')
    assert read_os_release(str(path)) == {
        "ID": "ubuntu",
        "VERSION_ID": "24.04",
        "PRETTY_NAME": "Ubuntu 24.04 LTS",
    }
    assert read_os_release(str(tmp_path / "missing")) == {}


def test_probe_from_host_runs(scratch_layout: Layout) -> None:
    probe = Probe.from_host(scratch_layout)
    assert probe.machine
    assert "/" in probe.disks
    assert probe.sb_version is None  # scratch layout has no sb binary
    assert probe.repo_ok is True
    assert probe.configs_present is False
