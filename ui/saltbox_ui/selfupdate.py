"""Update this app itself, from the web app.

How depends on how it was installed:

* from a source checkout (an editable install): pull the branch, reinstall the
  package if its dependencies changed, rebuild the web app;
* from a release wheel: install the newest wheel on the project's Releases page
  into the environment the daemon runs from.

Either way the daemon then has to restart to run the new code, which the
daemon does itself once the update job has finished (``needs_restart``).

``python -m saltbox_ui.selfupdate`` is the update job's command: it prints what
it does, line by line, and exits non-zero when a step fails.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any

from . import __version__
from .state.repos import RepoStatus, check_repo

PROJECT = "syms-dev/saltbox-ui"
LATEST_RELEASE = f"https://api.github.com/repos/{PROJECT}/releases/latest"
UNIT = "saltbox-ui.service"

Fetch = Callable[[str], Any]


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def source_dir(package: Path | None = None) -> Path | None:
    """The source tree this runs from, when it is an editable install; else ``None``."""
    root = (package or package_dir()).parent
    if (root / "pyproject.toml").is_file() and (root / "web" / "package.json").is_file():
        return root
    return None


def checkout_of(source: Path) -> Path | None:
    """The git checkout that holds ``source`` (it may be a folder inside a larger one)."""
    for folder in (source, *source.parents):
        if (folder / ".git").exists():
            return folder
    return None


def parse_version(text: str) -> tuple[int, ...]:
    """``"v0.1.10"`` → ``(0, 1, 10)``; anything that is not numbers sorts first."""
    parts = text.strip().lstrip("vV").split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return ()


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": "saltbox-ui"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def latest_release(fetch: Fetch = fetch_json) -> dict[str, str]:
    """The newest release's version and its wheel's address."""
    try:
        data = fetch(LATEST_RELEASE)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise RuntimeError(f"no release of {PROJECT} can be read (is it public?)") from error
        raise RuntimeError(f"GitHub answered {error.code}") from error
    except (OSError, ValueError) as error:
        raise RuntimeError(f"could not reach GitHub: {error}") from error
    wheel = next(
        (
            str(asset.get("browser_download_url"))
            for asset in data.get("assets") or []
            if str(asset.get("name", "")).endswith(".whl")
        ),
        "",
    )
    version = str(data.get("tag_name") or "").lstrip("vV")
    if not version or not wheel:
        raise RuntimeError("the latest release has no wheel")
    return {"version": version, "url": wheel}


def status(
    *,
    package: Path | None = None,
    repo_status: Callable[[Path], RepoStatus | None] = check_repo,
    fetch: Fetch = fetch_json,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    """How this app is installed and whether a newer version is there to update to."""
    result: dict[str, Any] = {
        "version": __version__,
        "mode": "wheel",
        "source": None,
        "latest": None,
        "update_available": False,
        "can_update": True,
        "detail": "",
        "checked_at": time.time(),
    }
    source = source_dir(package)
    if source is not None:
        result["mode"] = "source"
        checkout = checkout_of(source)
        found = repo_status(checkout) if checkout is not None else None
        if found is None:
            result.update(can_update=False, detail=f"{source} is not a git checkout")
            return result
        result["source"] = {
            "path": found.path,
            "branch": found.branch,
            "commit": found.commit,
            "remote_commit": found.remote_commit,
        }
        result["update_available"] = found.status == "update"
        result["detail"] = found.detail
        if found.status == "unknown":
            result["can_update"] = False
        elif which("npm") is None:
            result.update(
                can_update=False,
                detail="npm is not installed, so the web app cannot be rebuilt here",
            )
        return result
    try:
        latest = latest_release(fetch)
    except RuntimeError as error:
        result.update(can_update=False, detail=str(error))
        return result
    result["latest"] = latest
    result["update_available"] = parse_version(latest["version"]) > parse_version(__version__)
    return result


def needs_restart(loaded_commit: str | None, *, package: Path | None = None) -> bool:
    """Whether what is on disk is no longer what this process loaded."""
    source = source_dir(package)
    if source is not None:
        return loaded_commit is not None and head_commit(source) != loaded_commit
    try:
        return metadata.version("saltbox-ui") != __version__
    except metadata.PackageNotFoundError:
        return False


def head_commit(folder: Path) -> str | None:
    try:
        done = subprocess.run(
            ["git", "-c", f"safe.directory={checkout_of(folder) or folder}", "rev-parse", "HEAD"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def restart_daemon(delay: float = 1.5) -> None:
    """Ask systemd to restart the daemon in a moment, once the job's record is written."""
    import threading

    def restart() -> None:
        subprocess.run(["systemctl", "--no-block", "restart", UNIT], check=False, timeout=30)

    timer = threading.Timer(delay, restart)
    timer.daemon = True
    timer.start()


# -- the update itself, as the job's command -----------------------------------------------
def say(text: str) -> None:
    print(text, flush=True)


def step(args: list[str], *, cwd: Path | None = None, owner: os.stat_result | None = None) -> int:
    """Run one command, its output going to the job log. ``owner``: run it as that user."""
    say("$ " + " ".join(args))
    switch: dict[str, Any] = {}
    if owner is not None and os.geteuid() == 0 and owner.st_uid != 0:
        # Files git writes stay the checkout owner's, as they would with their own git pull.
        switch = {"user": owner.st_uid, "group": owner.st_gid, "extra_groups": []}
    try:
        return subprocess.run(args, cwd=cwd, check=False, **switch).returncode
    except OSError as error:
        say(f"could not run {args[0]}: {error}")
        return 127


def update_source(source: Path) -> int:
    checkout = checkout_of(source)
    if checkout is None:
        say(f"{source} is not a git checkout")
        return 1
    before = head_commit(source)
    safe = ["git", "-c", f"safe.directory={checkout}"]
    if step([*safe, "pull", "--ff-only"], cwd=checkout, owner=checkout.stat()) != 0:
        say("git could not fast-forward; the checkout has changes of its own to sort out first")
        return 1
    after = head_commit(source)
    if before == after:
        say("Already up to date.")
        return 0
    changed = subprocess.run(
        [*safe, "diff", "--name-only", f"{before}..{after}", "--", "pyproject.toml"],
        cwd=source,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if changed:
        say("The package's dependencies changed; installing them.")
        if step([sys.executable, "-m", "pip", "install", "--quiet", "-e", str(source)]) != 0:
            say("pip failed. The new code may need packages that are not installed.")
            return 1
    npm = shutil.which("npm")
    if npm is None:
        say("npm is not installed, so the web app was not rebuilt")
        return 1
    for arguments in (["ci", "--no-audit", "--no-fund"], ["run", "build"]):
        if step([npm, *arguments], cwd=source / "web") != 0:
            return 1
    say(f"Updated from {str(before)[:7]} to {str(after)[:7]}. The daemon restarts now.")
    return 0


def update_wheel(fetch: Fetch = fetch_json) -> int:
    try:
        latest = latest_release(fetch)
    except RuntimeError as error:
        say(str(error))
        return 1
    if parse_version(latest["version"]) <= parse_version(__version__):
        say(f"Already on the latest release ({__version__}).")
        return 0
    say(f"Installing saltbox-ui {latest['version']} over {__version__}.")
    if step([sys.executable, "-m", "pip", "install", "--upgrade", latest["url"]]) != 0:
        return 1
    say(f"Installed {latest['version']}. The daemon restarts now.")
    return 0


def main() -> int:
    source = source_dir()
    return update_source(source) if source is not None else update_wheel()


if __name__ == "__main__":
    raise SystemExit(main())
