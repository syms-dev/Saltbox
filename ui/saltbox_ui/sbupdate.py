"""Stand in for the terminal that ``sb update`` insists on.

``sb update`` refuses to start unless its output is a terminal, because it
can stop for a person twice: it shows new announcements in a full-screen
viewer that waits for ``q``, and it asks "Run all migration tags? (y/n)".
The daemon therefore runs it on a pseudo-terminal, and this module plays the
terminal's part:

* output is turned back into plain log lines (escape sequences removed);
* when the viewer opens, the announcements are read from the repositories'
  ``announcements.yml`` (the same before/after comparison sb makes), written
  to the log and kept for the job page, and the viewer is closed;
* the migration question is not answered here. It becomes the job's
  ``question`` and waits for the person using the app.

The behaviour mirrored here is sb's ``cmd/update.go`` and
``saltbox/announcements.go``.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .yamlio import load_plain

ALT_SCREEN_ON = "\x1b[?1049h"
ALT_SCREEN_OFF = "\x1b[?1049l"
ESCAPES = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"  # CSI: colours, cursor movement, modes
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC: titles, colour queries
    r"|\x1b[PX^_][^\x1b]*\x1b\\"  # DCS and friends
    r"|\x1b[()][0-9A-Za-z]"  # character sets
    r"|\x1b[@-Z\\-_=>]"  # two-character escapes
)
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
MIGRATION_HEADING = "The following tags need to be run to handle migrations:"
MIGRATION_PROMPT = re.compile(r"Run all migration tags\? \(y/n\):\s*$")
MIGRATION_ROW = re.compile(r"^\s*\d+\s+(\S+)\s+(\S+)\s+(\S+)\s*$")
INVALID_ANSWER = "Invalid input."
SELF_UPDATED = "Successfully updated sb CLI"
VIEWER_KEY_EVERY = 1.0
VIEWER_GIVE_UP = 60.0

Ask = Callable[[dict[str, Any]], bool]


def clean_line(raw: str) -> str:
    """One line as a person would read it: no escape sequences, last ``\\r`` rewrite wins."""
    text = ESCAPES.sub("", raw).rstrip("\r")
    if "\r" in text:
        text = text.rsplit("\r", 1)[1]
    return CONTROL.sub("", text).rstrip()


# -- announcements -----------------------------------------------------------------------
def read_announcements(repo: Path) -> list[dict[str, Any]] | None:
    """``announcements.yml`` of a checkout; ``None`` when it has none or it cannot be read."""
    path = repo / "announcements.yml"
    try:
        data = load_plain(path) if path.is_file() else None
    except Exception:  # a broken file must not stop an update
        return None
    if not isinstance(data, dict):
        return None
    items = data.get("announcements")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _applies(item: dict[str, Any]) -> bool:
    """sb shows an announcement only where its ``required_folder`` / ``required_file`` exist."""
    folder, file = item.get("required_folder"), item.get("required_file")
    if folder and not Path(str(folder)).is_dir():
        return False
    return not (file and not Path(str(file)).is_file())


def new_announcements(
    repo_name: str, before: list[dict[str, Any]] | None, after: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Announcements in ``after`` that ``before`` did not have, oldest first, as sb decides it."""
    if after is None:
        return []
    seen = {f"{item.get('date')}|{item.get('title')}" for item in before or []}
    found = []
    for item in after:
        if f"{item.get('date')}|{item.get('title')}" in seen or not _applies(item):
            continue
        migration = item.get("migration") if isinstance(item.get("migration"), dict) else {}
        tag = str(migration.get("tag") or "") if migration.get("required") else ""
        found.append(
            {
                "repo": repo_name,
                "date": str(item.get("date") or ""),
                "title": str(item.get("title") or ""),
                "message": str(item.get("message") or "").strip(),
                "migration": tag or None,
            }
        )
    return sorted(found, key=lambda a: a["date"])


# -- the terminal -------------------------------------------------------------------------
class UpdateTerminal:
    """What the job runner talks to while ``sb update`` runs on a pseudo-terminal.

    ``feed`` takes what sb wrote and returns finished log lines; ``keys``
    returns what to type. ``question`` is set while sb waits for a yes or no
    that only a person should give; ``answer`` gives it. With ``ask``, the
    question is put to that callable at once instead (the command line).
    """

    def __init__(
        self,
        repos: dict[str, Path],
        *,
        ask: Ask | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.repos = dict(repos)
        self.ask = ask
        self.clock = clock
        self.before = {name: read_announcements(path) for name, path in self.repos.items()}
        self.announcements: list[dict[str, Any]] = []
        self.question: dict[str, Any] | None = None
        self.rerun = False
        self.error: str | None = None
        self._lock = threading.Lock()
        self._buffer = ""
        self._outbox = b""
        self._in_viewer = False
        self._viewer_since = 0.0
        self._viewer_key_at = 0.0
        self._migrations: list[dict[str, str]] = []
        self._migration_text: list[str] = []
        self._collecting = False
        self._answer: bytes | None = None
        self._rejected = False
        self._retries = 0
        self._prompt_handled = False

    @classmethod
    def for_layout(cls, layout: Any, **options: Any) -> UpdateTerminal:
        return cls({"Saltbox": layout.repo, "Sandbox": layout.sandbox_repo}, **options)

    # -- what the runner calls ---------------------------------------------------------
    def restart(self) -> None:
        """A second run of the command (after sb updated itself) starts with a clean screen."""
        with self._lock:
            self._buffer, self._outbox = "", b""
            self._in_viewer, self._prompt_handled = False, False
            self._collecting, self._answer, self._rejected = False, None, False
            self.rerun, self.question = False, None

    def record(self) -> dict[str, Any]:
        """The fields this terminal adds to the job record."""
        with self._lock:
            return {"question": self.question, "announcements": list(self.announcements)}

    def keys(self) -> bytes:
        """Bytes to type into the terminal now."""
        with self._lock:
            if self._in_viewer:
                now = self.clock()
                if now - self._viewer_since > VIEWER_GIVE_UP:
                    self.error = "sb's announcement viewer did not close"
                elif now >= self._viewer_key_at:
                    self._outbox += b"q"
                    self._viewer_key_at = now + VIEWER_KEY_EVERY
            keys, self._outbox = self._outbox, b""
            return keys

    def answer(self, yes: bool) -> bool:
        """Answer the pending question. Returns False when there is none."""
        with self._lock:
            if self.question is None:
                return False
            self._send_answer(yes)
            return True

    def feed(self, text: str) -> list[str]:
        """Take terminal output; return the log lines it completes."""
        lines: list[str] = []
        ask: dict[str, Any] | None = None
        with self._lock:
            self._buffer += text
            while True:
                if self._in_viewer:
                    end = self._buffer.find(ALT_SCREEN_OFF)
                    if end < 0:
                        # Keep only a tail long enough to hold a split closing sequence.
                        self._buffer = self._buffer[-len(ALT_SCREEN_OFF) :]
                        break
                    self._buffer = self._buffer[end + len(ALT_SCREEN_OFF) :]
                    self._in_viewer = False
                    continue
                start = self._buffer.find(ALT_SCREEN_ON)
                head = self._buffer if start < 0 else self._buffer[:start]
                consumed = self._take_lines(head, lines, final=start >= 0)
                if start < 0:
                    self._buffer = self._buffer[consumed:]
                    break
                self._buffer = self._buffer[start + len(ALT_SCREEN_ON) :]
                self._open_viewer(lines)
            if not self._in_viewer:
                ask = self._check_prompt()
        if ask is not None and self.ask is not None:
            yes = bool(self.ask(ask))
            with self._lock:
                self._send_answer(yes)
        return lines

    def flush(self) -> list[str]:
        """Whatever is left on the last line when the command ends."""
        with self._lock:
            rest, self._buffer = clean_line(self._buffer), ""
            self.question = None
            return [rest] if rest and not self._in_viewer else []

    # -- internals ---------------------------------------------------------------------
    def _take_lines(self, text: str, lines: list[str], *, final: bool) -> int:
        """Move the complete lines of ``text`` to ``lines``; returns how much was used."""
        consumed = 0
        while True:
            end = text.find("\n", consumed)
            if end < 0:
                break
            self._line(clean_line(text[consumed:end]), lines)
            consumed = end + 1
        if final and text[consumed:].strip():
            self._line(clean_line(text[consumed:]), lines)
            consumed = len(text)
        return consumed

    def _line(self, line: str, lines: list[str]) -> None:
        self._prompt_handled = False  # a finished line means the prompt moved on
        if SELF_UPDATED in line:
            self.rerun = True
        if INVALID_ANSWER in line:
            self._rejected = True
        if line.strip() == MIGRATION_HEADING:
            self._collecting, self._migrations, self._migration_text = True, [], []
        elif self._collecting and line.strip():
            self._migration_text.append(line)
            row = MIGRATION_ROW.match(line)
            if row:
                self._migrations.append(
                    {"repo": row.group(1), "tag": row.group(2), "date": row.group(3)}
                )
        lines.append(line)

    def _open_viewer(self, lines: list[str]) -> None:
        """sb opened its announcement viewer: log what it is showing, then close it."""
        self._in_viewer = True
        self._viewer_since = self.clock()
        self._viewer_key_at = self._viewer_since
        found: list[dict[str, Any]] = []
        for name, path in self.repos.items():
            found += new_announcements(name, self.before.get(name), read_announcements(path))
        known = {(a["repo"], a["date"], a["title"]) for a in self.announcements}
        fresh = [a for a in found if (a["repo"], a["date"], a["title"]) not in known]
        self.announcements += fresh
        if not found:
            lines.append("sb showed new announcements; read announcements.yml in the checkouts.")
        for item in fresh:
            lines.append("")
            lines.append(f"== {item['repo']} announcement, {item['date']}: {item['title']} ==")
            lines += item["message"].splitlines()
        if fresh:
            lines.append("")

    def _check_prompt(self) -> dict[str, Any] | None:
        """Raise the migration question when sb is waiting at its prompt."""
        if self._prompt_handled or not MIGRATION_PROMPT.search(clean_line(self._buffer)):
            return None
        self._prompt_handled = True
        self._collecting = False
        rejected, self._rejected = self._rejected, False
        if self._answer is not None and rejected and self._retries < 3:
            # sb read something else before the answer (a stray key) and asks again.
            self._retries += 1
            self._outbox += self._answer
            return None
        self.question = {
            "kind": "migrations",
            "migrations": list(self._migrations),
            "text": "\n".join(self._migration_text),
        }
        return self.question

    def _send_answer(self, yes: bool) -> None:
        self._answer = b"y\n" if yes else b"n\n"
        self._retries, self._rejected = 0, False
        self._outbox += self._answer
        self.question = None
