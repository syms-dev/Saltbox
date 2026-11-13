"""Find errors that keep coming back in the apps' logs, and explain the ones we know.

Every app logs errors now and then; one that repeats is worth a look. This
reads the last day of each container's log, keeps the lines that are errors,
groups the ones that are the same apart from numbers, paths and times, and
reports the groups that recur. A short list of known messages (below) comes
with what it means and what to do, taken from Saltbox's own roles and the
apps' behaviour. Nothing here changes anything on the server.
"""

from __future__ import annotations

import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from .state.containers import Runner

SINCE = "24h"
TAIL = 3000
MIN_REPEATS = 3  # an unexplained error must recur this often to be listed
MAX_GROUPS = 5  # per container
MAX_MESSAGE = 400

ERROR = re.compile(
    r"\b(?:ERROR|ERR|FATAL|CRITICAL|CRIT|PANIC)\b"  # the usual level words
    r"|\[(?:Error|Fatal)\]"  # Sonarr, Radarr, Prowlarr
    r"|level=(?:error|fatal|panic)\b"  # logfmt
    r'|"level":\s*"(?:error|fatal|panic)"'  # JSON
    r"|^panic:|Traceback \(most recent call last\)"
)
DOCKER_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\S*\s?")
# The app's own timestamp at the start of a line, in the shapes the Saltbox apps use.
OWN_TIME = re.compile(
    r"^\[?(?:\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
    r"|[A-Z][a-z]{2} +\d{1,2} \d{2}:\d{2}:\d{2}"
    r"|\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\]?\s*(?:[-|]\s*)?"
)
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
PATH = re.compile(r"(?<![\w.])/(?:[^\s'\",:;)\]]+)")
HEX = re.compile(r"\b[0-9a-f]{8,}\b")
NUMBER = re.compile(r"\d+")


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: re.Pattern[str]
    title: str
    meaning: str
    fix: tuple[str, ...]
    # "problem": something is not working; "notice": harmless, but explains the noise.
    severity: str = "problem"
    containers: tuple[str, ...] = ()  # name prefixes it applies to; empty for any

    def matches(self, container: str, line: str) -> bool:
        if self.containers and not container.startswith(self.containers):
            return False
        return self.pattern.search(line) is not None


RULES: tuple[Rule, ...] = (
    Rule(
        "autoscan-anchor",
        re.compile(r"Anchor files unavailable"),
        "Autoscan is holding back every scan",
        "Autoscan tells Plex about new files only while its anchor file exists. Saltbox sets "
        "that to /mnt/unionfs/mounted.bin, a file meant to prove that cloud storage is mounted, "
        "so that a failed mount never makes Plex think your media was deleted. The file is "
        "missing, so new downloads are not being scanned into Plex by Autoscan.",
        (
            "If you use cloud storage, a remote is not mounted: look at Mounts on this page.",
            "If your media is only on this server's own disks, create the file once as your "
            "Saltbox user: `touch /mnt/local/mounted.bin`. It then shows up as "
            "/mnt/unionfs/mounted.bin.",
            "Or remove the `anchors:` entry from /opt/autoscan/config.yml and restart Autoscan.",
        ),
        containers=("autoscan",),
    ),
    Rule(
        "bazarr-not-a-video",
        re.compile(r"is not a valid video extension"),
        "Bazarr cannot read a file in your library",
        "Bazarr tried to read the video details of a file that is not a video it understands, "
        "such as a disc image (.iso). It skips that file; nothing else is affected.",
        (
            "Replace the file named in the log with a normal video file (.mkv, .mp4).",
            "To stop disc images being downloaded, use the TRaSH quality profiles (Connect "
            "apps, Quality profiles): they reject BR-DISK releases.",
        ),
        severity="notice",
        containers=("bazarr",),
    ),
    Rule(
        "disk-full",
        re.compile(r"No space left on device|ENOSPC", re.IGNORECASE),
        "A disk is full",
        "The app could not write because the disk it writes to has no space left.",
        ("See which disk under Storage on this page, and free space on it.",),
    ),
    Rule(
        "database-damaged",
        re.compile(r"database disk image is malformed"),
        "An app's database is damaged",
        "SQLite reports that the app's database file is corrupt. The app can misbehave or "
        "lose changes until it is repaired.",
        (
            "For Sonarr, Radarr, Lidarr, Whisparr, Prowlarr and Tautulli, Saltbox checks, backs "
            "up and repairs the database with `sb install arr-db` (Activity, Run tags).",
            "For Plex, `sb install plex-db` checks and optimises its database.",
            "Other apps: restore the database from the app's own backups.",
        ),
    ),
    Rule(
        "permission-denied",
        re.compile(r"Permission denied|EACCES|UnauthorizedAccessException"),
        "An app is not allowed to read or write a file",
        "A file or folder the app needs belongs to another user, often after files were "
        "copied in as root.",
        (
            "`sb install fix-permissions` (Activity, Run tags) gives /mnt/local, /opt and your "
            "home folder back to your Saltbox user.",
        ),
    ),
    Rule(
        "cloudflare-blocked",
        re.compile(r"blocked by CloudFlare Protection", re.IGNORECASE),
        "An indexer is behind Cloudflare's bot check",
        "Prowlarr cannot search an indexer because Cloudflare blocks automated requests to it.",
        (
            "Install FlareSolverr and run Connect apps: it adds FlareSolverr to Prowlarr with "
            "the tag flaresolverr.",
            "In Prowlarr, add that tag to the indexer.",
        ),
        containers=("prowlarr",),
    ),
)


def is_error(line: str) -> bool:
    return ERROR.search(line) is not None


def split_time(raw: str) -> tuple[str, str]:
    """Docker's timestamp (``--timestamps``) and the rest of the line."""
    match = DOCKER_TIME.match(raw)
    if match is None:
        return "", raw
    return match.group(1) + "Z", raw[match.end() :]


def clean(line: str) -> str:
    """The message without colour codes or the app's own timestamp."""
    return OWN_TIME.sub("", ANSI.sub("", line).strip(), count=1).strip()


def signature(message: str) -> str:
    """What stays the same between two occurrences of one error."""
    text = PATH.sub("<path>", message)
    text = HEX.sub("<id>", text)
    return NUMBER.sub("#", text)


def analyse(container: str, lines: list[str]) -> list[dict[str, Any]]:
    """Recurring and known errors in one container's log lines, most frequent first."""
    groups: dict[str, dict[str, Any]] = {}
    for raw in lines:
        seen, text = split_time(raw)
        error = is_error(text)
        message = clean(text)
        # A message known for one app counts whatever level the app logs it at; the
        # general ones (disk full, permissions) only when the line is an error.
        rule = next(
            (r for r in RULES if (error or r.containers) and r.matches(container, message)), None
        )
        if rule is None and not error:
            continue
        key = f"rule:{rule.id}" if rule else signature(message)
        group = groups.setdefault(key, {"count": 0, "rule": rule})
        group["count"] += 1
        group["message"] = message[:MAX_MESSAGE]
        group["last_seen"] = seen
    found = [
        {
            "message": group["message"],
            "count": group["count"],
            "last_seen": group["last_seen"],
            "rule": _rule_view(group["rule"]),
        }
        for group in groups.values()
        if group["rule"] is not None or group["count"] >= MIN_REPEATS
    ]
    found.sort(key=lambda g: (g["rule"] is None, -g["count"]))
    return found[:MAX_GROUPS]


def _rule_view(rule: Rule | None) -> dict[str, Any] | None:
    if rule is None:
        return None
    return {
        "id": rule.id,
        "title": rule.title,
        "meaning": rule.meaning,
        "fix": list(rule.fix),
        "severity": rule.severity,
    }


def read_log(name: str, runner: Runner | None = None) -> list[str]:
    """The last day of a container's log (at most ``TAIL`` lines), with Docker's timestamps."""
    args = ["docker", "logs", "--since", SINCE, "--tail", str(TAIL), "--timestamps", "--", name]
    if runner is not None:
        code, output = runner(args)
        return output.splitlines() if code == 0 else []
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return result.stdout.splitlines() if result.returncode == 0 else []


def scan(names: list[str], runner: Runner | None = None) -> dict[str, list[dict[str, Any]]]:
    """``analyse`` for every container named, reading the logs a few at a time."""
    if not names:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(names))) as pool:
        logs = list(pool.map(lambda name: read_log(name, runner), names))
    results = {name: analyse(name, lines) for name, lines in zip(names, logs, strict=True)}
    return {name: groups for name, groups in results.items() if groups}
