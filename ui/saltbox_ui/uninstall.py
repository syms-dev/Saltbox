"""Uninstall an app: remove its containers, and its settings folder only when asked.

``sb`` has no uninstall. What a role leaves on the server is its container
(and any it creates beside it), its folder under the appdata path, and a DNS
record. Removing the container is what stops the app using memory and CPU;
the folder holds its settings and database, so it is deleted only on request
and only when it is a plain folder directly under the appdata path.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from .state.containers import Runner, _run_long

DEPENDS_ON_LABEL = "com.github.saltbox.depends_on"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class UninstallError(RuntimeError):
    pass


def dependents(names: set[str], containers: list[dict[str, Any]]) -> list[str]:
    """Why removing ``names`` would break something else that stays, one sentence each."""
    reasons = []
    for container in containers:
        other = str(container.get("name", ""))
        if other in names:
            continue
        mode = str(container.get("network_mode", ""))
        if mode.startswith("container:") and mode.split(":", 1)[1] in names:
            reasons.append(f"{other} runs inside {mode.split(':', 1)[1]}'s network")
            continue
        labels = container.get("labels") or {}
        needed = {n.strip() for n in str(labels.get(DEPENDS_ON_LABEL, "")).split(",")}
        for name in sorted(needed & names):
            reasons.append(f"{other} needs {name} to start")
    return reasons


def data_folder(appdata: Path, name: str) -> Path | None:
    """The settings folder of instance ``name``, when it is safe to delete: a real folder
    directly under ``appdata``, not a link and not reached through ``..``."""
    if not SAFE_NAME.match(name):
        return None
    path = appdata / name
    if path.is_symlink() or not path.is_dir():
        return None
    if path.resolve().parent != appdata.resolve():
        return None
    return path


def remove_container(name: str, runner: Runner | None = None) -> None:
    code, output = (runner or _run_long)(["docker", "rm", "--force", "--", name])
    if code != 0:
        raise UninstallError(output.strip() or f"docker rm {name} failed")


def delete_folder(appdata: Path, name: str) -> Path:
    path = data_folder(appdata, name)
    if path is None:
        raise UninstallError(f"{appdata / name} is not a folder this can delete")
    try:
        shutil.rmtree(path)
    except OSError as error:
        raise UninstallError(f"could not delete {path}: {error}") from error
    return path
