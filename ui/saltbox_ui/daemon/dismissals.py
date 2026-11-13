"""Issues someone has looked at and chosen to stop being told about.

A failing drive can stay in service for months and a harmless log message can
repeat for ever. Each issue the daemon reports carries a key that names what
is wrong (for a drive: which checks and attributes fail); dismissing stores
that key on the server, so it holds for every browser. When the issue changes
(another attribute starts failing) its key changes and it is shown again.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

MAX_KEY = 300
MAX_ENTRIES = 500


class Dismissals:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def all(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def has(self, key: str) -> bool:
        return key in self.all()

    def add(self, key: str, label: str = "") -> None:
        if not key or len(key) > MAX_KEY:
            raise ValueError("not an issue this server reported")
        with self._lock:
            entries = self.all()
            entries[key] = {"at": time.time(), "label": label[:MAX_KEY]}
            # Oldest out first, so the file cannot grow without end.
            kept = sorted(entries.items(), key=lambda item: item[1].get("at", 0))[-MAX_ENTRIES:]
            self._save(dict(kept))

    def remove(self, key: str) -> bool:
        with self._lock:
            entries = self.all()
            if key not in entries:
                return False
            del entries[key]
            self._save(entries)
            return True

    def _save(self, entries: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, indent=1), encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(self.path)
