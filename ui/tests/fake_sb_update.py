"""A stand-in for ``sb update`` that behaves at the terminal the way sb does.

It follows sb's ``cmd/update.go`` and ``saltbox/announcements.go`` in the
ways that matter to whoever drives it:

- it refuses to run unless its output is a terminal;
- a new announcement appears in the checkout's ``announcements.yml`` (as an
  update that brought one would leave it), and is shown in a full-screen viewer
  (alternate screen, raw keyboard) that stays until ``q``, Esc or Ctrl+C;
- it then lists the migration tags and asks "Run all migration tags? (y/n)",
  repeating the question until it reads y, yes, n or no.

Run from the checkout, as ``sb`` is. ``announcements.yml`` is put back on the
way out so a test box can run it again. Environment:

- ``FAKE_SB_SELF_UPDATE=<path>``: the first run "updates sb itself" and exits,
  as sb does, asking to be run again; the file marks that it happened.
- ``FAKE_SB_QUIET=1``: an update that brings no announcement.
"""

from __future__ import annotations

import os
import signal
import sys
import termios
import time
import tty
from pathlib import Path

ANNOUNCEMENT = """
  - date: "2031-01-01"
    title: "Test migration"
    migration:
      required: true
      tag: e2e-migration
    message: |
      ## Test announcement

      Something moved, and existing installs need a migration.
"""
BLUE, RESET = "\x1b[94m", "\x1b[0m"


def say(text: str = "") -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def viewer() -> None:
    """Full screen until a quit key, like sb's Bubble Tea announcement viewer."""
    saved = termios.tcgetattr(0)
    tty.setraw(0)
    os.write(1, b"\x1b[?1049h\x1b[?25l\x1b[2J\x1b[H# Saltbox Announcement\r\n\r\n  q: Quit")
    try:
        while os.read(0, 1) not in (b"q", b"\x1b", b"\x03", b""):
            pass
    finally:
        os.write(1, b"\x1b[?25h\x1b[?1049l")
        termios.tcsetattr(0, termios.TCSADRAIN, saved)


def approve() -> bool:
    while True:
        sys.stdout.write("\nRun all migration tags? (y/n): ")
        sys.stdout.flush()
        line = sys.stdin.readline()
        if not line:
            say("Error: failed to read migration approval: EOF")
            raise SystemExit(1)
        answer = line.strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        say("Invalid input. Please enter 'y' (yes) or 'n' (no).")


def main() -> int:
    if not os.isatty(1):
        say("\n   ERROR  \n")
        say("  update command requires an interactive terminal (TTY not available)\n")
        return 1
    if "--verbose" not in sys.argv:
        say("fake sb: without --verbose the real one draws spinners instead of lines")
        return 3
    marker = os.environ.get("FAKE_SB_SELF_UPDATE")
    if marker and not Path(marker).exists():
        Path(marker).write_text("updated\n")
        say(f"{BLUE}Successfully updated sb CLI to version: 9.9.9{RESET}")
        say("\x1b[93mRe-run the update command to update Saltbox\x1b[0m")
        return 0

    say("Updating apt package cache...")
    say(f"{BLUE}Saltbox: Updating the current branch 'test'{RESET}")
    say("Updating Saltbox...")
    sys.stdout.write("Receiving objects:  50% (1/2)\rReceiving objects: 100% (2/2), done.\n")
    sys.stdout.flush()
    announcements = Path.cwd() / "announcements.yml"
    existed = announcements.exists()
    original = announcements.read_text(encoding="utf-8") if existed else "announcements:\n"

    def restore(*_: object) -> None:
        if existed:
            announcements.write_text(original, encoding="utf-8")
        else:
            announcements.unlink(missing_ok=True)

    def stopped(*_: object) -> None:
        restore()
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, stopped)
    signal.signal(signal.SIGHUP, stopped)
    try:
        say("Saltbox updated")
        if not os.environ.get("FAKE_SB_QUIET"):
            announcements.write_text(original.rstrip("\n") + "\n" + ANNOUNCEMENT, encoding="utf-8")
            say(f"{BLUE}Displaying new announcements{RESET}")
            viewer()
            say("\nThe following tags need to be run to handle migrations:")
            say("\n  #  Repo      Tag             Announcement Date")
            say("  -  -------   -------------   -----------------")
            say("  1  Saltbox   e2e-migration   2031-01-01")
            if approve():
                say(f"{BLUE}Starting migration execution{RESET}")
                say(f"{BLUE}Running migration 'e2e-migration' for Saltbox repository{RESET}")
                time.sleep(0.2)
        say("Validating Saltbox configuration...")
        say("Validating Saltbox configuration")
    finally:
        restore()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
