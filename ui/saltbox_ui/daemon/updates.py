"""Image update checks for the daemon: cached on disk, refreshed in the background."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

from ..layout import Layout
from ..state.containers import list_containers
from ..state.updates import ImageStatus, check_updates

CACHE_FILE = "updates.json"
MAX_AGE = 6 * 3600


class UpdateService:
    def __init__(
        self,
        layout: Layout,
        *,
        containers: Callable[[], list[dict[str, Any]]] | None = None,
        checker: Callable[[list[dict[str, Any]]], dict[str, ImageStatus]] | None = None,
        clock: Callable[[], float] = time.time,
        max_age: float = MAX_AGE,
    ):
        self.path = layout.state_dir / CACHE_FILE
        self.containers = containers or list_containers
        self.checker = checker or check_updates
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
        data["running"] = self.running
        data["error"] = self.error
        return data

    def _write(self, images: dict[str, ImageStatus]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = {
            "checked_at": self.clock(),
            "images": {ref: status.as_dict() for ref, status in images.items()},
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
        try:
            self._write(self.checker(self.containers()))
            self.error = ""
        except Exception as error:  # keep the last good result, report why this one failed
            self.error = str(error)

    def ensure_fresh(self) -> None:
        checked = self.cached().get("checked_at")
        if not checked or self.clock() - float(checked) > self.max_age:
            self.refresh()

    # -- lookups -----------------------------------------------------------------
    def status_by_container(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for status in self.cached().get("images", {}).values():
            for name in status.get("containers", []):
                result[name] = status
        return result
