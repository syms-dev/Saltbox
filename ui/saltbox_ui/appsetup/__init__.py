"""Connect the installed apps to each other: the post-install setup step.

``AppSetup`` finds what is installed, builds the list of connections the
Saltbox docs describe, checks each one against the app's API and applies the
missing ones. The TUI, ``sbx setup`` and the daemon all use it.
"""

from __future__ import annotations

import os
import pwd
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from ..layout import Layout
from .discover import Discovery, Resolver, Service, discover, resolve_hosts
from .http import SetupError, Transport
from .tasks import SetupContext, Task, apply_all, build_tasks, check_all, summarize

__all__ = [
    "AppSetup",
    "Discovery",
    "Service",
    "SetupError",
    "Task",
    "summarize",
]


def owned_dir_maker(user: str) -> Callable[[Path], None]:
    """mkdir -p that hands every folder it creates to the Saltbox user."""

    def make(path: Path) -> None:
        missing = []
        current = Path(path)
        while not current.exists() and current != current.parent:
            missing.append(current)
            current = current.parent
        path.mkdir(parents=True, exist_ok=True)
        try:
            entry = pwd.getpwnam(user)
        except KeyError:
            return
        if os.geteuid() != 0:
            return
        for created in missing:
            os.chown(created, entry.pw_uid, entry.pw_gid)

    return make


def docker_logs(name: str) -> str:
    """The recent log of a container, or an empty string when Docker is not available."""
    if shutil.which("docker") is None:
        return ""
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", "300", name],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout + result.stderr


class AppSetup:
    def __init__(
        self,
        layout: Layout,
        *,
        transport: Transport | None = None,
        resolver: Resolver | None = None,
        ensure_dir: Callable[[Path], None] | None = None,
        log_reader: Callable[[str], str] | None = None,
    ):
        self.layout = layout
        self.log_reader = log_reader or docker_logs
        self.transport = transport
        self.resolver = resolver
        self.ensure_dir = ensure_dir

    def discover(self) -> Discovery:
        found = discover(self.layout)
        resolve_hosts(found, self.resolver)
        return found

    def tasks(self) -> list[Task]:
        found = self.discover()
        ctx = SetupContext(
            found,
            transport=self.transport,
            ensure_dir=self.ensure_dir or owned_dir_maker(found.user),
            log_reader=self.log_reader,
        )
        return build_tasks(ctx)

    def status(self) -> list[Task]:
        return check_all(self.tasks())

    def apply(self, on_task: Callable[[Task], None] | None = None) -> list[Task]:
        return apply_all(self.tasks(), on_task)
