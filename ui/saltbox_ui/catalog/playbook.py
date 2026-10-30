"""Read the role list and tags out of ``saltbox.yml`` or ``sandbox.yml``.

The playbook is plain YAML, but the comment markers (``# Core``,
``# Apps Start``, ``# Apps End``) carry meaning Saltbox's own CI relies on,
so the section of each role is taken from the text as well.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..yamlio import load_plain_text

ROLE_LINE_RE = re.compile(r"^\s*-\s*\{\s*role:\s*([A-Za-z0-9_]+)")


@dataclass(frozen=True)
class RoleEntry:
    role: str
    tags: tuple[str, ...]
    section: str  # "pre", "core", "apps", "other"
    when: tuple[str, ...] = ()
    line: int = 0

    @property
    def install_tag(self) -> str | None:
        """The user-facing tag: the first tag that is not a meta or reset tag."""
        candidates = [t for t in self.tags if t not in META_TAGS and t != "never"]
        if not candidates:
            return None
        plain = [t for t in candidates if "-" not in t or t == candidates[0]]
        return plain[0] if plain else candidates[0]

    @property
    def always(self) -> bool:
        return "always" in self.tags

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "tags": list(self.tags),
            "section": self.section,
            "when": list(self.when),
            "install_tag": self.install_tag,
        }


META_TAGS = {"core", "saltbox", "mediabox", "feederbox", "preinstall", "always"}


def parse_playbook(path: Path) -> list[RoleEntry]:
    text = Path(path).read_text(encoding="utf-8")
    sections = _sections_by_line(text)
    data = load_plain_text(text)
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ValueError(f"{path} does not look like a playbook")
    roles = data[0].get("roles") or []
    entries: list[RoleEntry] = []
    line_lookup = _role_lines(text)
    for raw in roles:
        if isinstance(raw, str):
            name, tags, when = raw, [], []
        elif isinstance(raw, dict):
            name = str(raw.get("role"))
            tags = raw.get("tags") or []
            when = raw.get("when") or []
            if isinstance(tags, str):
                tags = [tags]
            if isinstance(when, str):
                when = [when]
        else:
            continue
        line = line_lookup.get(name, 0)
        entries.append(
            RoleEntry(
                role=name,
                tags=tuple(str(t) for t in tags),
                section=sections.get(line, "other"),
                when=tuple(str(w) for w in when),
                line=line,
            )
        )
    return entries


def _role_lines(text: str) -> dict[str, int]:
    found: dict[str, int] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        match = ROLE_LINE_RE.match(line)
        if match and match.group(1) not in found:
            found[match.group(1)] = number
    return found


def _sections_by_line(text: str) -> dict[int, str]:
    """Map each role line number to its playbook section."""
    section = "pre"
    result: dict[int, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            marker = stripped.lstrip("#").strip().lower()
            if marker == "core":
                section = "core"
            elif marker == "apps start":
                section = "apps"
            elif marker == "apps end":
                section = "other"
            continue
        if ROLE_LINE_RE.match(line):
            result[number] = section
    return result


@dataclass
class TagIndex:
    """Tags grouped the way ``sb list`` shows them."""

    entries: list[RoleEntry] = field(default_factory=list)

    def all_tags(self) -> list[str]:
        tags: set[str] = set()
        for entry in self.entries:
            tags.update(t for t in entry.tags if t not in {"always", "never"})
        return sorted(tags)

    def by_tag(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for entry in self.entries:
            for tag in entry.tags:
                result.setdefault(tag, []).append(entry.role)
        return result
