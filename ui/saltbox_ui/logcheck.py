"""Find errors that keep coming back in the apps' logs, and explain the ones we know.

Every app logs errors now and then; one that repeats is worth a look. This
reads the last day of each container's log, keeps the lines that are errors,
groups the ones that are the same apart from numbers, paths and times, and
reports the groups that recur. A short list of known messages (below) comes
with what it means and what to do, taken from Saltbox's own roles and the
apps' behaviour. Nothing here changes anything on the server.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .state.containers import Runner

SINCE = "24h"
TAIL = 3000
MIN_REPEATS = 3  # an unexplained error must recur this often to be listed
MAX_GROUPS = 5  # per container
MAX_MESSAGE = 400
MAX_SUBJECTS = 10

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
    # "problem": something is not working (shown on Home); "minor": one thing works less
    # well; "notice": harmless, but explains the noise.
    severity: str = "problem"
    containers: tuple[str, ...] = ()  # name prefixes it applies to; empty for any
    # What to do instead on a server whose media is only on its own disks.
    fix_local: tuple[str, ...] = ()
    # Picks out what each occurrence is about (a file), to list them.
    subject: re.Pattern[str] | None = None
    # A fix the daemon can make itself, offered when it is safe on this server.
    action: str = ""

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
            "This server has cloud storage set up, so the likely cause is a remote that is not "
            "mounted: look at Mounts on this page.",
            "If the remote is mounted and has no mounted.bin, put an empty file with that name "
            "at the top of the remote.",
        ),
        containers=("autoscan",),
        fix_local=(
            "This server has no cloud storage set up, so nothing will ever create that file: "
            "create it once on the local disks, where it shows up as /mnt/unionfs/mounted.bin. "
            "The button below does that, or run `touch /mnt/local/mounted.bin` as your Saltbox "
            "user.",
            "Autoscan sends the scans it has been holding once the file is there.",
        ),
        action="create-anchor",
    ),
    Rule(
        "bazarr-not-a-video",
        re.compile(r"is not a valid video extension"),
        "Bazarr cannot read a file in your library",
        "Bazarr tried to read the video details of a file that is not a video it understands, "
        "such as a disc image (.iso). It skips that file; nothing else is affected.",
        (
            "Replace each file listed here with a normal video file (.mkv, .mp4): in Sonarr or "
            "Radarr, delete the file and search again.",
            "To stop disc images being downloaded, use the TRaSH quality profiles (Connect "
            "apps, Quality profiles): they reject BR-DISK releases.",
        ),
        severity="notice",
        containers=("bazarr",),
        subject=re.compile(r"for this file: (.+)$"),
    ),
    Rule(
        "flaresolverr-timeout",
        re.compile(r"Error solving the challenge"),
        "FlareSolverr could not get past a Cloudflare check",
        "FlareSolverr opens a real browser to pass Cloudflare's bot check for an indexer, and "
        "gave up when its time ran out. Searches of that indexer fail; other indexers are not "
        "affected. Each attempt keeps a browser open for a minute, which is why FlareSolverr "
        "uses several hundred MB of memory while this goes on.",
        (
            "Cloudflare changes its check often and FlareSolverr does not always keep up: "
            "update FlareSolverr and see whether it passes again.",
            "If one indexer keeps failing, take the flaresolverr tag off it or disable it in "
            "Prowlarr, so FlareSolverr stops trying.",
        ),
        severity="minor",
        containers=("flaresolverr",),
    ),
    Rule(
        "authelia-idle-timeout",
        re.compile(r"Request timeout occurred while handling request from client"),
        "Authelia closed a connection that sent nothing",
        "Something opened a connection to Authelia and sent no request within its time limit, "
        "so Authelia closed it and logged a 408. When the client is an address inside Docker's "
        "network, it is usually Traefik or a health check holding a connection open.",
        (
            "Nothing to do while signing in works.",
            "If sign-in pages hang or time out, restart Authelia and check again.",
        ),
        severity="notice",
        containers=("authelia",),
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


def issue_key(container: str, rule: Rule | None, signed: str) -> str:
    """Names one recurring error of one container, for dismissing it."""
    what = rule.id if rule else hashlib.sha1(signed.encode()).hexdigest()[:12]
    return f"log:{container}:{what}"


def analyse(
    container: str,
    lines: list[str],
    *,
    cloud: bool = True,
    roots: tuple[Path, Path] | None = None,
) -> list[dict[str, Any]]:
    """Recurring and known errors in one container's log lines, most frequent first.

    ``cloud`` says whether the server has cloud storage set up; some advice
    differs without it, and one fix is only offered then. ``roots`` are the
    merged and the local media folders (``/mnt/unionfs``, ``/mnt/local``).
    """
    unionfs, local = roots or (UNIONFS, LOCAL)
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
        signed = signature(message)
        key = issue_key(container, rule, signed)
        group = groups.setdefault(key, {"count": 0, "rule": rule, "subjects": {}})
        group["count"] += 1
        group["message"] = message[:MAX_MESSAGE]
        group["full"] = message
        group["last_seen"] = seen
        if rule is not None and rule.subject is not None:
            found = rule.subject.search(message)
            if found:
                group["subjects"][found.group(1).strip()] = True
    result = []
    for key, group in groups.items():
        rule = group["rule"]
        if rule is None and group["count"] < MIN_REPEATS:
            continue
        subjects = list(group["subjects"])
        result.append(
            {
                "key": key,
                "message": group["message"],
                "count": group["count"],
                "last_seen": group["last_seen"],
                "rule": _rule_view(rule, cloud),
                "subjects": subjects[:MAX_SUBJECTS],
                "more_subjects": max(0, len(subjects) - MAX_SUBJECTS),
                "action": _action_view(rule, group["full"], cloud, unionfs, local),
            }
        )
    result.sort(key=lambda g: (g["rule"] is None, -g["count"]))
    return result[:MAX_GROUPS]


def _rule_view(rule: Rule | None, cloud: bool) -> dict[str, Any] | None:
    if rule is None:
        return None
    return {
        "id": rule.id,
        "title": rule.title,
        "meaning": rule.meaning,
        "fix": list(rule.fix_local if rule.fix_local and not cloud else rule.fix),
        "severity": rule.severity,
    }


# -- fixes the daemon can make ----------------------------------------------------------------
UNIONFS = Path("/mnt/unionfs")
LOCAL = Path("/mnt/local")
ANCHORS = re.compile(r"missing_anchors=(\[[^\]]*\])")


def missing_anchors(message: str) -> list[str]:
    """The anchor files Autoscan says it cannot find."""
    found = ANCHORS.search(message)
    if found is None:
        return []
    try:
        names = json.loads(found.group(1))
    except ValueError:
        return []
    return [str(name) for name in names if isinstance(name, str)]


def anchor_targets(message: str, unionfs: Path, local: Path) -> list[Path]:
    """Where to create each missing anchor on the local disks, when that is possible.

    The merged folder (``/mnt/unionfs``) shows what is in the local one
    (``/mnt/local``), so a file created there appears where Autoscan looks. Only
    anchors inside an existing folder of the local tree qualify.
    """
    targets = []
    for anchor in missing_anchors(message):
        try:
            relative = Path(anchor).relative_to(unionfs)
        except ValueError:
            return []
        if ".." in relative.parts or not relative.parts:
            return []
        target = local / relative
        if not target.parent.is_dir() or target.is_symlink():
            return []
        targets.append(target)
    return targets


def _action_view(
    rule: Rule | None, message: str, cloud: bool, unionfs: Path, local: Path
) -> dict[str, Any] | None:
    """The one-click fix for this finding, when there is one and it is safe here."""
    if rule is None or rule.action != "create-anchor" or cloud:
        # With cloud storage a missing anchor means a mount is down; creating it locally
        # would defeat the protection it exists for.
        return None
    targets = anchor_targets(message, unionfs, local)
    if not targets:
        return None
    paths = [str(target) for target in targets]
    return {
        "id": rule.action,
        "label": "Create the anchor file",
        "detail": f"Creates an empty {', '.join(paths)}, owned by whoever owns {local}.",
        "targets": paths,
    }


def create_anchors(targets: list[str], local: Path = LOCAL) -> list[str]:
    """Create the anchor files a scan offered to create. Returns what now exists.

    Each must still be a plain path inside an existing folder of ``local``:
    the list comes back from a browser, so it is checked again here.
    """
    if not targets:
        raise ValueError("nothing to create")
    paths = []
    for name in targets:
        target = Path(name)
        try:
            relative = target.relative_to(local)
        except ValueError as error:
            raise ValueError(f"{name} is not under {local}") from error
        if ".." in relative.parts or not relative.parts:
            raise ValueError(f"{name} is not a file under {local}")
        if not target.parent.is_dir() or target.is_symlink():
            raise ValueError(f"{target.parent} is not a folder")
        paths.append(target)
    owner = local.stat()
    for target in paths:
        target.touch(exist_ok=True)
        if os.geteuid() == 0:
            os.chown(target, owner.st_uid, owner.st_gid)
    return [str(target) for target in paths]


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


def scan(
    names: list[str],
    runner: Runner | None = None,
    *,
    cloud: bool = True,
    roots: tuple[Path, Path] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """``analyse`` for every container named, reading the logs a few at a time."""
    if not names:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(names))) as pool:
        logs = list(pool.map(lambda name: read_log(name, runner), names))
    results = {
        name: analyse(name, lines, cloud=cloud, roots=roots)
        for name, lines in zip(names, logs, strict=True)
    }
    return {name: groups for name, groups in results.items() if groups}
