import fcntl
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from saltbox_ui.layout import Layout
from saltbox_ui.runner import JobRunning, SbRunner, trust_repos


def test_install_command_building(scratch_layout: Layout):
    runner = SbRunner(scratch_layout, sb=Path("/usr/local/bin/sb"))
    assert runner.install_command(["core", "plex"]) == ["/usr/local/bin/sb", "install", "core,plex"]
    assert runner.install_command(
        ["sonarr"],
        skip_tags=["settings"],
        extra_vars=["sonarr_name=sonarr2"],
        verbosity=2,
        no_cache=True,
    ) == [
        "/usr/local/bin/sb",
        "install",
        "sonarr",
        "--skip-tags",
        "settings",
        "--extra-vars",
        "sonarr_name=sonarr2",
        "-vv",
        "--no-cache",
    ]
    with pytest.raises(ValueError):
        runner.install_command([" "])
    assert runner.update_command() == [
        "/usr/local/bin/sb",
        "update",
        "--verbose",
        "--keep-branch",
    ]


def test_run_streams_and_records(scratch_layout: Layout, fake_sb: Path):
    runner = SbRunner(scratch_layout, sb=fake_sb)
    lines = []
    job = runner.install(["core"], on_line=lines.append)
    assert job.status == "succeeded"
    assert job.returncode == 0
    assert "sb args: install core" in lines
    assert "stderr line" in lines
    assert job.started_at and job.finished_at
    log = runner.log(job.id)
    assert log.startswith(f"$ {fake_sb} install core")
    assert runner.job(job.id).command == job.command
    assert [j.id for j in runner.jobs()] == [job.id]
    assert runner.is_locked() is None


def test_run_failure_and_missing_binary(scratch_layout: Layout, fake_sb: Path):
    runner = SbRunner(
        scratch_layout, sb=fake_sb, env={"FAKE_SB_EXIT": "3", "PATH": "/bin:/usr/bin"}
    )
    job = runner.update()
    assert job.status == "failed"
    assert job.returncode == 3
    missing = SbRunner(scratch_layout, sb=scratch_layout.repo / "no-such-sb")
    job = missing.run([str(missing.sb), "list"], kind="list")
    assert job.status == "failed"
    assert job.returncode == 127
    assert "failed to start" in runner.log(job.id) or "failed to start" in missing.log(job.id)


def test_lock_prevents_concurrent_jobs(scratch_layout: Layout, fake_sb: Path):
    runner = SbRunner(scratch_layout, sb=fake_sb)
    scratch_layout.state_dir.mkdir(parents=True, exist_ok=True)
    with open(scratch_layout.lock_file, "w") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        holder.write('{"job": "other"}')
        holder.flush()
        with pytest.raises(JobRunning):
            runner.install(["core"])
        assert runner.is_locked() == {"job": "other"}
    assert runner.is_locked() is None


def test_trust_repos_appends_to_existing_git_config():
    env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.pager", "GIT_CONFIG_VALUE_0": "cat"}
    trust_repos(env, [Path("/srv/git/saltbox"), Path("/opt/sandbox"), Path("/srv/git/saltbox")])
    assert env["GIT_CONFIG_COUNT"] == "3"
    assert env["GIT_CONFIG_KEY_0"] == "core.pager"
    assert (env["GIT_CONFIG_KEY_1"], env["GIT_CONFIG_VALUE_1"]) == (
        "safe.directory",
        "/srv/git/saltbox",
    )
    assert (env["GIT_CONFIG_KEY_2"], env["GIT_CONFIG_VALUE_2"]) == (
        "safe.directory",
        "/opt/sandbox",
    )
    trust_repos(env, [Path("/opt/sandbox")])
    assert env["GIT_CONFIG_COUNT"] == "3"


@pytest.mark.skipif(
    os.geteuid() != 0 or shutil.which("git") is None, reason="needs root and git to chown a repo"
)
def test_trust_repos_lets_root_use_a_repo_owned_by_another_user(tmp_path: Path):
    repo = tmp_path / "saltbox"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for path in [repo, *repo.rglob("*")]:
        os.chown(path, 65534, 65534)
    base = {k: v for k, v in os.environ.items() if not k.startswith(("SUDO_", "GIT_CONFIG"))}
    base["HOME"] = str(tmp_path)  # no global config with its own safe.directory
    command = ["git", "-C", str(repo), "rev-parse", "--git-dir"]
    refused = subprocess.run(command, env=base, capture_output=True, text=True)
    assert refused.returncode != 0 and "dubious ownership" in refused.stderr
    allowed = subprocess.run(command, env=trust_repos(dict(base), [repo]), capture_output=True)
    assert allowed.returncode == 0


def test_jobs_get_a_home_when_systemd_gives_none(scratch_layout: Layout, tmp_path: Path):
    """systemd starts the daemon without HOME; sb's first task runs `git config --global`."""
    script = tmp_path / "bin" / "sb-home"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        '#!/bin/sh\necho "home=$HOME"\ngit config --global --get-all safe.directory\n'
    )
    script.chmod(0o755)
    runner = SbRunner(scratch_layout, sb=script, env={"PATH": "/usr/bin:/bin"})
    lines: list[str] = []
    runner.run([str(script)], kind="install", on_line=lines.append)
    assert lines[0] == "home=" + __import__("pwd").getpwuid(os.geteuid()).pw_dir
    assert not any("HOME not set" in line for line in lines)


def test_systemd_unit_sets_home():
    from saltbox_ui.daemon.install import systemd_unit

    assert "Environment=HOME=/root" in systemd_unit("/usr/local/bin/saltbox-uid")


def test_cancel_stops_what_sb_started(scratch_layout: Layout, tmp_path: Path):
    """sb runs ansible-playbook as a child; cancelling only sb left it running with the log
    pipe open, so the job never finished."""
    import threading
    import time

    script = tmp_path / "bin" / "sb-tree"
    script.parent.mkdir(parents=True, exist_ok=True)
    marker = tmp_path / "child-survived"
    script.write_text(f"#!/bin/sh\necho started\n(sleep 3; touch {marker}) &\nsleep 30\n")
    script.chmod(0o755)
    runner = SbRunner(scratch_layout, sb=script)
    lines: list[str] = []
    jobs: list = []
    thread = threading.Thread(
        target=lambda: jobs.append(runner.run([str(script)], kind="install", on_line=lines.append))
    )
    thread.start()
    deadline = time.time() + 5
    while "started" not in lines and time.time() < deadline:
        time.sleep(0.02)
    began = time.time()
    assert runner.cancel() is True
    thread.join(timeout=10)
    assert not thread.is_alive(), "the job kept running after cancel"
    assert time.time() - began < 5
    assert jobs[0].status == "interrupted"
    time.sleep(3.5)
    assert not marker.exists(), "a process sb started outlived the cancel"


def test_job_records_and_logs_are_private(scratch_layout: Layout, fake_sb: Path):
    scratch_layout.jobs_dir.mkdir(parents=True)
    scratch_layout.jobs_dir.chmod(0o755)  # as an older version left it
    job = SbRunner(scratch_layout, sb=fake_sb).install(["core"])
    assert scratch_layout.jobs_dir.stat().st_mode & 0o777 == 0o700
    assert Path(job.log_path).stat().st_mode & 0o777 == 0o600
