"""Updating the app itself: what it reports, what the update job does, and the restart."""

import subprocess
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saltbox_ui import __version__, selfupdate
from saltbox_ui.daemon import Services, create_app
from saltbox_ui.layout import Layout
from saltbox_ui.state.repos import RepoStatus

WHEEL = "https://github.com/syms-dev/saltbox-ui/releases/download/v9.9.9/saltbox_ui-9.9.9.whl"


def release(version: str = "9.9.9") -> dict:
    return {
        "tag_name": f"v{version}",
        "assets": [
            {"name": "notes.txt", "browser_download_url": "https://example.invalid/notes.txt"},
            {"name": f"saltbox_ui-{version}-py3-none-any.whl", "browser_download_url": WHEEL},
        ],
    }


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


@pytest.fixture
def checkout(tmp_path: Path) -> tuple[Path, Path]:
    """A checkout with the app's source in ``ui/`` (as in the Saltbox fork) and its upstream."""
    upstream = tmp_path / "upstream.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(upstream))
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(upstream), str(work))
    ui = work / "ui"
    (ui / "saltbox_ui").mkdir(parents=True)
    (ui / "web").mkdir()
    (ui / "pyproject.toml").write_text("[project]\nname = 'saltbox-ui'\n")
    (ui / "web" / "package.json").write_text("{}\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "first")
    git(work, "push", "-q", "-u", "origin", "HEAD:main")
    clone = tmp_path / "server"
    git(tmp_path, "clone", "-q", str(upstream), str(clone))
    return clone, work


def push_change(work: Path, name: str, text: str) -> None:
    (work / "ui" / name).write_text(text)
    git(work, "add", "-A")
    git(work, "commit", "-qm", f"change {name}")
    git(work, "push", "-q", "origin", "HEAD:main")


def test_versions_compare_as_numbers() -> None:
    assert selfupdate.parse_version("v0.1.10") > selfupdate.parse_version("0.1.9")
    assert selfupdate.parse_version("1.0.0") > selfupdate.parse_version("v0.9.12")
    assert selfupdate.parse_version("nightly") == ()


def test_latest_release_is_the_wheel_of_the_newest_tag() -> None:
    assert selfupdate.latest_release(lambda url: release()) == {"version": "9.9.9", "url": WHEEL}
    with pytest.raises(RuntimeError, match="has no wheel"):
        selfupdate.latest_release(lambda url: {"tag_name": "v1.0.0", "assets": []})

    def private(url: str):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    with pytest.raises(RuntimeError, match="is it public"):
        selfupdate.latest_release(private)

    def offline(url: str):
        raise OSError("no route to host")

    with pytest.raises(RuntimeError, match="could not reach GitHub"):
        selfupdate.latest_release(offline)


def test_status_of_an_install_from_a_release_wheel(tmp_path: Path) -> None:
    package = tmp_path / "site-packages" / "saltbox_ui"
    package.mkdir(parents=True)
    newer = selfupdate.status(package=package, fetch=lambda url: release())
    assert newer["mode"] == "wheel" and newer["version"] == __version__
    assert newer["update_available"] is True and newer["can_update"] is True
    assert newer["latest"] == {"version": "9.9.9", "url": WHEEL}
    same = selfupdate.status(package=package, fetch=lambda url: release(__version__))
    assert same["update_available"] is False

    def private(url: str):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    unknown = selfupdate.status(package=package, fetch=private)
    assert unknown["can_update"] is False and "is it public" in unknown["detail"]


def test_status_of_an_install_from_a_source_checkout(checkout) -> None:
    clone, _ = checkout
    package = clone / "ui" / "saltbox_ui"
    behind = RepoStatus("server", str(clone), "main", "1111111", "2222222", status="update")
    found = selfupdate.status(
        package=package, repo_status=lambda path: behind, which=lambda name: "/usr/bin/npm"
    )
    assert found["mode"] == "source" and found["update_available"] is True
    assert found["source"] == {
        "path": str(clone),
        "branch": "main",
        "commit": "1111111",
        "remote_commit": "2222222",
    }
    no_npm = selfupdate.status(
        package=package, repo_status=lambda path: behind, which=lambda name: None
    )
    assert no_npm["can_update"] is False and "npm is not installed" in no_npm["detail"]
    # The real thing, against the real checkout: nothing new upstream yet.
    real = selfupdate.status(package=package, which=lambda name: "/usr/bin/npm")
    assert real["update_available"] is False and real["source"]["branch"] == "main"


@pytest.fixture
def fake_npm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log = tmp_path / "npm.log"
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text(f'#!/bin/sh\necho "$PWD: npm $*" >> {log}\nexit "${{FAKE_NPM_EXIT:-0}}"\n')
    npm.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    return log


def test_updating_a_source_checkout_pulls_and_rebuilds(checkout, fake_npm: Path, capfd) -> None:
    clone, work = checkout
    source = clone / "ui"
    loaded = selfupdate.head_commit(source)
    assert selfupdate.update_source(source) == 0
    assert "Already up to date." in capfd.readouterr().out
    assert not fake_npm.exists()  # nothing changed: nothing rebuilt
    assert selfupdate.needs_restart(loaded, package=source / "saltbox_ui") is False

    push_change(work, "saltbox_ui/new.py", "x = 1\n")
    assert selfupdate.update_source(source) == 0
    assert (source / "saltbox_ui" / "new.py").exists()
    assert fake_npm.read_text().splitlines() == [
        f"{source}/web: npm ci --no-audit --no-fund",
        f"{source}/web: npm run build",
    ]
    out = capfd.readouterr().out
    assert "pip" not in out  # dependencies did not change
    assert "The daemon restarts now." in out
    assert selfupdate.needs_restart(loaded, package=source / "saltbox_ui") is True


def test_a_failing_build_or_a_diverged_checkout_fails_the_update(
    checkout, fake_npm: Path, monkeypatch: pytest.MonkeyPatch, capfd
) -> None:
    clone, work = checkout
    source = clone / "ui"
    push_change(work, "saltbox_ui/new.py", "x = 1\n")
    monkeypatch.setenv("FAKE_NPM_EXIT", "1")
    assert selfupdate.update_source(source) == 1

    # A commit of the server's own that the branch lacks: git will not fast-forward over it.
    (source / "local.txt").write_text("mine\n")
    git(clone, "add", "-A")
    git(clone, "commit", "-qm", "local change")
    push_change(work, "saltbox_ui/other.py", "y = 2\n")
    assert selfupdate.update_source(source) == 1
    assert "could not fast-forward" in capfd.readouterr().out


def test_changed_dependencies_are_installed_before_the_rebuild(
    checkout, fake_npm: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone, work = checkout
    source = clone / "ui"
    push_change(work, "pyproject.toml", "[project]\nname = 'saltbox-ui'\nversion = '2'\n")
    ran: list[list[str]] = []
    real_step = selfupdate.step

    def step(args: list[str], **options):
        ran.append(args)
        return 0 if "pip" in args else real_step(args, **options)

    monkeypatch.setattr(selfupdate, "step", step)
    assert selfupdate.update_source(source) == 0
    pip = next(args for args in ran if "pip" in args)
    assert pip[1:] == ["-m", "pip", "install", "--quiet", "-e", str(source)]
    assert ran.index(pip) < ran.index(next(args for args in ran if args[-1] == "build"))


def test_updating_a_wheel_install_installs_the_newest_wheel(
    monkeypatch: pytest.MonkeyPatch, capfd
) -> None:
    ran: list[list[str]] = []
    monkeypatch.setattr(selfupdate, "step", lambda args, **options: ran.append(args) or 0)
    assert selfupdate.update_wheel(lambda url: release()) == 0
    assert ran[0][1:] == ["-m", "pip", "install", "--upgrade", WHEEL]
    assert f"Installing saltbox-ui 9.9.9 over {__version__}." in capfd.readouterr().out
    ran.clear()
    assert selfupdate.update_wheel(lambda url: release(__version__)) == 0
    assert ran == [] and "Already on the latest release" in capfd.readouterr().out


def test_the_update_runs_as_a_job_and_the_daemon_restarts_after_it(
    scratch_layout: Layout, fake_sb: Path
) -> None:
    restarts: list[int] = []
    available = {
        "version": "0.1.0",
        "mode": "wheel",
        "source": None,
        "latest": {"version": "9.9.9", "url": WHEEL},
        "update_available": True,
        "can_update": True,
        "detail": "",
        "checked_at": 0,
    }
    services = Services(
        scratch_layout,
        self_status=lambda: dict(available),
        self_command=["sh", "-c", "echo Installing saltbox-ui 9.9.9; echo done"],
        restart=lambda: restarts.append(1),
    )
    client = TestClient(create_app(services=services))
    meta = client.get("/api/meta").json()
    assert meta["started_at"] > 0 and "build" in meta
    assert client.get("/api/self").json()["latest"]["version"] == "9.9.9"

    job = client.post("/api/self/update").json()
    assert job["kind"] == "selfupdate"
    services.jobs.wait(10)
    finished = client.get(f"/api/jobs/{job['id']}").json()
    assert finished["status"] == "succeeded"
    assert "Installing saltbox-ui 9.9.9" in client.get(f"/api/jobs/{job['id']}/log").json()["text"]
    assert restarts == [1]

    # A failed update leaves the daemon as it is.
    services.self_command = ["sh", "-c", "echo pip failed; exit 1"]
    failed = client.post("/api/self/update").json()
    services.jobs.wait(10)
    assert client.get(f"/api/jobs/{failed['id']}").json()["status"] == "failed"
    assert restarts == [1]

    available["update_available"] = False
    assert client.post("/api/self/update").status_code == 409
    available.update(update_available=True, can_update=False, detail="npm is not installed")
    refused = client.post("/api/self/update")
    assert refused.status_code == 409 and refused.json()["detail"] == "npm is not installed"
