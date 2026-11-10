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
    assert runner.update_command() == ["/usr/local/bin/sb", "update"]


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
