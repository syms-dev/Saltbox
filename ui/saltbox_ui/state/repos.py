"""Whether the Saltbox checkouts are behind the branch they track.

``sb update`` resets each checkout to its upstream branch. To tell whether
that would change anything, the commit the upstream branch points at is read
with ``git ls-remote``, which writes nothing into the checkout (a fetch run as
root would leave root-owned objects in a repository the Saltbox user owns).
When that commit is the local ``HEAD``, or a commit ``HEAD`` already contains,
the checkout is current; otherwise ``sb update`` would bring in new commits.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

GitRunner = Callable[[Path, list[str]], tuple[int, str]]

CREDENTIALS_RE = re.compile(r"(?<=://)[^/@]+@")


def run_git(repo: Path, args: list[str]) -> tuple[int, str]:
    """Run git in ``repo`` as whoever the daemon is, trusting that checkout only."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    try:
        done = subprocess.run(
            ["git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, str(error)
    return done.returncode, (done.stdout if done.returncode == 0 else done.stderr).strip()


@dataclass
class RepoStatus:
    name: str
    path: str
    branch: str = ""
    commit: str = ""
    remote_commit: str = ""
    source: str = ""
    status: str = "unknown"  # current | update | unknown
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_repo(path: Path, run: GitRunner = run_git) -> RepoStatus | None:
    """Status of one checkout, or ``None`` when ``path`` is not a git checkout."""
    if not (path / ".git").exists():
        return None
    status = RepoStatus(name=path.name, path=str(path))
    code, head = run(path, ["rev-parse", "HEAD"])
    if code != 0:
        status.detail = f"cannot read HEAD: {head}"
        return status
    status.commit = head[:7]
    code, branch = run(path, ["symbolic-ref", "--short", "-q", "HEAD"])
    if code != 0 or not branch:
        status.detail = "detached HEAD; sb update needs a branch"
        return status
    status.branch = branch
    remote = _config(path, run, f"branch.{branch}.remote") or "origin"
    merge = _config(path, run, f"branch.{branch}.merge") or f"refs/heads/{branch}"
    code, url = run(path, ["remote", "get-url", remote])
    status.source = CREDENTIALS_RE.sub("", url) if code == 0 else remote
    code, out = run(path, ["ls-remote", "--exit-code", remote, merge])
    if code != 0 or not out:
        status.detail = f"cannot read {merge.removeprefix('refs/heads/')} from {status.source}"
        return status
    remote_head = out.split()[0]
    status.remote_commit = remote_head[:7]
    if remote_head == head or _contains(path, run, head, remote_head):
        status.status = "current"
        if remote_head != head:
            status.detail = "has local commits the remote branch lacks"
        return status
    status.status = "update"
    status.detail = (
        f"{status.source} {branch} is at {status.remote_commit}, this checkout at {status.commit}"
    )
    return status


def check_repos(paths: Iterable[Path], run: GitRunner = run_git) -> list[RepoStatus]:
    return [status for path in paths if (status := check_repo(path, run)) is not None]


def _config(path: Path, run: GitRunner, key: str) -> str:
    code, value = run(path, ["config", "--get", key])
    return value if code == 0 else ""


def _contains(path: Path, run: GitRunner, head: str, commit: str) -> bool:
    """Whether ``head`` already includes ``commit`` (only answerable if it is local)."""
    code, _ = run(path, ["cat-file", "-e", f"{commit}^{{commit}}"])
    if code != 0:
        return False
    code, _ = run(path, ["merge-base", "--is-ancestor", commit, head])
    return code == 0
