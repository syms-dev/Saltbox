#!/usr/bin/env python3
"""Generate ``saltbox_ui/catalog/data/apps.json`` from a docs repository checkout.

Reads the frontmatter of ``docs/apps/*.md`` and ``docs/sandbox/apps/*.md`` for
titles, summaries, links and app links, and ``docs/apps/index.md`` for the
category each app is filed under.

Usage: build_catalog.py /path/to/saltyorg-docs [output.json]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from ruamel.yaml import YAML

HEADING_RE = re.compile(r"^(#{2,6})\s+(.*?)\s*$")
ROW_RE = re.compile(r"^\|\s*\[([^\]]+)\]\(([^)]+)\)")
DECOR_RE = re.compile(r":[a-z0-9_+-]+:|\{[^}]*\}")


def read_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    return YAML(typ="safe").load(text[3:end]) or {}


def categories_from_index(index: Path) -> dict[str, list[str]]:
    """Doc path (relative to docs/apps) -> category paths."""
    levels: dict[int, str] = {}
    result: dict[str, list[str]] = {}
    for line in index.read_text(encoding="utf-8").splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            depth = len(heading.group(1))
            title = DECOR_RE.sub("", heading.group(2)).strip()
            levels[depth] = title
            for deeper in [d for d in levels if d > depth]:
                del levels[deeper]
            continue
        row = ROW_RE.match(line)
        if row:
            target = row.group(2)
            path = target
            category = " > ".join(levels[d] for d in sorted(levels))
            result.setdefault(path, []).append(category)
    return result


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    docs = Path(sys.argv[1])
    output = (
        Path(sys.argv[2])
        if len(sys.argv) > 2
        else Path(__file__).resolve().parent.parent
        / "saltbox_ui"
        / "catalog"
        / "data"
        / "apps.json"
    )
    categories = categories_from_index(docs / "docs" / "apps" / "index.md")
    apps = []
    for repo, folder, prefix in (
        ("saltbox", docs / "docs" / "apps", ""),
        ("sandbox", docs / "docs" / "sandbox" / "apps", "../sandbox/apps/"),
    ):
        for page in sorted(folder.glob("*.md")):
            if page.name == "index.md":
                continue
            fm = read_frontmatter(page)
            auto = fm.get("saltbox_automation") or {}
            desc = auto.get("project_description") or {}
            role = page.stem
            rel = f"{prefix}{page.name}"
            apps.append(
                {
                    "role": role,
                    "repo": repo,
                    "title": desc.get("name") or fm.get("title") or role,
                    "summary": (desc.get("summary") or "").strip(),
                    "link": desc.get("link") or "",
                    "categories": categories.get(rel, []),
                    "docs_url": (
                        f"https://docs.saltbox.dev/apps/{role}/"
                        if repo == "saltbox"
                        else f"https://docs.saltbox.dev/sandbox/apps/{role}/"
                    ),
                    "app_links": [
                        {
                            "name": link.get("name", ""),
                            "url": link.get("url") or "",
                            "purpose": link.get("purpose", ""),
                        }
                        for link in auto.get("app_links") or []
                    ],
                    "status": fm.get("status", ""),
                }
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"apps": apps}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {len(apps)} apps to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
