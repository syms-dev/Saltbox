"""Update checks for the daemon (app images and the Saltbox checkouts), cached on disk."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

from ..layout import Layout
from ..state.containers import list_containers
from ..state.repos import RepoStatus, check_repos
from ..state.updates import ImageStatus, check_updates

CACHE_FILE = "updates.json"
CACHE_VERSION = 2  # 2: added the Saltbox checkouts
MAX_AGE = 6 * 3600


class UpdateService:
    def __init__(
        self,
        layout: Layout,
        *,
        containers: Callable[[], list[dict[str, Any]]] | None = None,
        checker: Callable[[list[dict[str, Any]]], dict[str, ImageStatus]] | None = None,
        repos: Callable[[], list[RepoStatus]] | None = None,
        clock: Callable[[], float] = time.time,
        max_age: float = MAX_AGE,
    ):
        self.path = layout.state_dir / CACHE_FILE
        self.containers = containers or list_containers
        self.checker = checker or check_updates
        self.repos = repos or (
            lambda: check_repos([layout.repo, layout.sandbox_repo, layout.saltbox_mod_repo])
        )
        self.clock = clock
        self.max_age = max_age
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.error = ""

    # -- cache -----------------------------------------------------------------
    def cached(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {"checked_at": None, "images": {}}
        data.setdefault("repos", [])
        data["running"] = self.running
        data["error"] = self.error
        return data

    def _write(self, images: dict[str, Any], repos: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = {
            "version": CACHE_VERSION,
            "checked_at": self.clock(),
            "images": images,
            "repos": repos,
        }
        tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    # -- refresh ---------------------------------------------------------------
    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())

    def refresh(self, *, wait: bool = False) -> bool:
        """Start a check unless one is running; returns whether one was started."""
        with self._lock:
            if self.running:
                return False
            self._thread = threading.Thread(target=self._run, name="update-check", daemon=True)
            self._thread.start()
        if wait:
            self.wait()
        return True

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _run(self) -> None:
        """Check images and checkouts; a part that fails keeps its last good result."""
        previous = self.cached()
        errors: list[str] = []
        images, repos = previous.get("images", {}), previous.get("repos", [])
        try:
            images = {ref: s.as_dict() for ref, s in self.checker(self.containers()).items()}
        except Exception as error:
            errors.append(f"images: {error}")
        try:
            repos = [status.as_dict() for status in self.repos()]
        except Exception as error:
            errors.append(f"saltbox: {error}")
        try:
            self._write(images, repos)
        except OSError as error:
            errors.append(f"cache: {error}")
        self.error = "; ".join(errors)

    def ensure_fresh(self) -> None:
        cached = self.cached()
        checked = cached.get("checked_at")
        stale = not checked or self.clock() - float(checked) > self.max_age
        if stale or cached.get("version") != CACHE_VERSION:
            self.refresh()

    # -- lookups -----------------------------------------------------------------
    def status_by_container(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for status in self.cached().get("images", {}).values():
            for name in status.get("containers", []):
                result[name] = status
        return result
