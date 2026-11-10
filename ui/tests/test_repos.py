"""Checkout status against a real upstream: a bare repository standing in for GitHub."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from saltbox_ui.state.repos import check_repo, check_repos

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def git(cwd: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "HOME": str(cwd),
        "PATH": "/usr/bin:/bin",
    }
    done = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    git(repo, "add", name)
    git(repo, "commit", "-qm", name)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def checkouts(tmp_path: Path) -> tuple[Path, Path, Path]:
    """An upstream, the box's checkout of it, and a second clone that pushes upstream."""
    upstream = tmp_path / "upstream.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(upstream))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(upstream), str(seed))
    git(seed, "checkout", "-qb", "main")
    commit(seed, "a")
    git(seed, "push", "-q", "origin", "main")
    box = tmp_path / "saltbox"
    git(tmp_path, "clone", "-q", "-b", "main", str(upstream), str(box))
    return upstream, box, seed


def test_current_checkout(checkouts) -> None:
    _, box, _ = checkouts
    status = check_repo(box)
    assert status is not None
    assert (status.name, status.branch, status.status) == ("saltbox", "main", "current")
    assert status.commit == status.remote_commit


def test_upstream_moved_on(checkouts) -> None:
    _, box, seed = checkouts
    new = commit(seed, "b")
    git(seed, "push", "-q", "origin", "main")
    status = check_repo(box)
    assert status is not None and status.status == "update"
    assert status.remote_commit == new[:7]
    assert "main is at" in status.detail
    # ls-remote wrote nothing into the checkout
    assert subprocess.run(["git", "-C", str(box), "cat-file", "-e", new]).returncode != 0


def test_local_commits_ahead_are_current(checkouts) -> None:
    _, box, _ = checkouts
    commit(box, "local")
    status = check_repo(box)
    assert status is not None and status.status == "current"
    assert "local commits" in status.detail


def test_unreachable_remote_and_missing_checkout(checkouts, tmp_path: Path) -> None:
    upstream, box, _ = checkouts
    shutil.rmtree(upstream)
    status = check_repo(box)
    assert status is not None and status.status == "unknown"
    assert "cannot read main" in status.detail
    assert check_repos([tmp_path / "nope", box])[0].name == "saltbox"


def test_credentials_are_not_shown(checkouts) -> None:
    _, box, _ = checkouts
    git(box, "remote", "set-url", "origin", "https://user:token@github.invalid/o/r.git")
    status = check_repo(box)
    assert status is not None and status.source == "https://github.invalid/o/r.git"
