"""The app catalog.

Combines three sources:

- the playbooks (which roles exist and which tags install them),
- role defaults (instances support, settings fields),
- bundled docs metadata (``data/apps.json``: titles, summaries, links and
  categories generated from the Saltbox docs repository).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cached_property
from importlib import resources
from pathlib import Path
from typing import Any

from ..layout import Layout
from ..yamlio import load_plain
from .defaults import RoleDefaults, parse_role_defaults
from .playbook import RoleEntry, parse_playbook

MAIN_TAG_ROLES = {
    "saltbox": "saltbox_roles",
    "mediabox": "mediabox_roles",
    "feederbox": "feederbox_roles",
}
SELECTOR_ROLES = {
    "media_server": "media_servers_enabled",
    "download_clients": "download_clients_enabled",
    "download_indexers": "download_indexers_enabled",
}


@dataclass
class App:
    role: str
    repo: str  # "saltbox" or "sandbox"
    tags: list[str]
    install_tag: str | None
    section: str
    title: str
    summary: str = ""
    link: str = ""
    categories: list[str] = field(default_factory=list)
    docs_url: str = ""
    app_links: list[dict[str, str]] = field(default_factory=list)
    supports_instances: bool = False
    default_instances: list[str] = field(default_factory=list)
    main_tags: list[str] = field(default_factory=list)
    selector: str | None = None
    when: list[str] = field(default_factory=list)

    @property
    def sb_tag(self) -> str | None:
        """The tag as typed after ``sb install``."""
        if self.install_tag is None:
            return None
        return f"sandbox-{self.install_tag}" if self.repo == "sandbox" else self.install_tag

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "repo": self.repo,
            "tags": self.tags,
            "install_tag": self.install_tag,
            "sb_tag": self.sb_tag,
            "section": self.section,
            "title": self.title,
            "summary": self.summary,
            "link": self.link,
            "categories": self.categories,
            "docs_url": self.docs_url,
            "app_links": self.app_links,
            "supports_instances": self.supports_instances,
            "default_instances": self.default_instances,
            "main_tags": self.main_tags,
            "selector": self.selector,
            "when": self.when,
        }


def load_bundled_metadata() -> dict[str, dict[str, Any]]:
    """Docs-derived metadata keyed by ``repo/role``."""
    try:
        text = resources.files("saltbox_ui.catalog.data").joinpath("apps.json").read_text()
    except (FileNotFoundError, OSError):
        return {}
    data = json.loads(text)
    return {f"{item['repo']}/{item['role']}": item for item in data.get("apps", [])}


class Catalog:
    def __init__(self, layout: Layout, metadata: dict[str, dict[str, Any]] | None = None):
        self.layout = layout
        self.metadata = load_bundled_metadata() if metadata is None else metadata

    # -- playbooks -------------------------------------------------------------
    @cached_property
    def saltbox_roles(self) -> list[RoleEntry]:
        return parse_playbook(self.layout.playbook)

    @cached_property
    def sandbox_roles(self) -> list[RoleEntry]:
        if not self.layout.sandbox_playbook.exists():
            return []
        return parse_playbook(self.layout.sandbox_playbook)

    def role_dir(self, repo: str, role: str) -> Path:
        base = self.layout.roles_dir if repo == "saltbox" else self.layout.sandbox_repo / "roles"
        return base / role

    def defaults(self, role: str, repo: str = "saltbox") -> RoleDefaults | None:
        path = self.role_dir(repo, role) / "defaults" / "main.yml"
        if not path.exists():
            return None
        return parse_role_defaults(role, path)

    # -- profiles --------------------------------------------------------------
    @cached_property
    def profiles(self) -> dict[str, list[str]]:
        """Default role lists for the main tags and the selector roles."""
        result: dict[str, list[str]] = {}
        for role, var in list(MAIN_TAG_ROLES.items()) + list(SELECTOR_ROLES.items()):
            source = "main_tags" if role in MAIN_TAG_ROLES else role
            path = self.layout.roles_dir / source / "defaults" / "main.yml"
            if not path.exists():
                continue
            data = load_plain(path) or {}
            value = data.get(var)
            if isinstance(value, list):
                result[var] = [str(v) for v in value]
        return result

    # -- apps ------------------------------------------------------------------
    def apps(self, *, include_hidden: bool = False) -> list[App]:
        apps: list[App] = []
        apps.extend(self._apps_for("saltbox", self.saltbox_roles, include_hidden))
        apps.extend(self._apps_for("sandbox", self.sandbox_roles, include_hidden))
        return apps

    def app(self, role: str, repo: str | None = None) -> App | None:
        for candidate in self.apps(include_hidden=True):
            if candidate.role == role and (repo is None or candidate.repo == repo):
                return candidate
        return None

    def _apps_for(self, repo: str, entries: list[RoleEntry], include_hidden: bool) -> list[App]:
        profiles = self.profiles
        membership: dict[str, list[str]] = {}
        for tag, var in MAIN_TAG_ROLES.items():
            for role in profiles.get(var, []):
                membership.setdefault(role, []).append(tag)
        selector_of: dict[str, str] = {}
        for selector, var in SELECTOR_ROLES.items():
            for role in profiles.get(var, []):
                selector_of[role] = var
                for tag in membership.get(selector, []):
                    membership.setdefault(role, []).append(tag)
        result: list[App] = []
        for entry in entries:
            if entry.section not in {"apps", "core"} and not include_hidden:
                continue
            if entry.section == "core" and not include_hidden:
                continue
            meta = self.metadata.get(f"{repo}/{entry.role}", {})
            defaults = self.defaults(entry.role, repo)
            result.append(
                App(
                    role=entry.role,
                    repo=repo,
                    tags=list(entry.tags),
                    install_tag=entry.install_tag,
                    section=entry.section,
                    title=meta.get("title") or entry.role.replace("_", " ").title(),
                    summary=meta.get("summary", ""),
                    link=meta.get("link", ""),
                    categories=list(meta.get("categories", [])),
                    docs_url=meta.get("docs_url", ""),
                    app_links=list(meta.get("app_links", [])),
                    supports_instances=bool(defaults and defaults.supports_instances),
                    default_instances=list(defaults.default_instances) if defaults else [],
                    main_tags=sorted(set(membership.get(entry.role, []))),
                    selector=selector_of.get(entry.role),
                    when=list(entry.when),
                )
            )
        return result

    def categories(self) -> dict[str, list[str]]:
        """Category path -> roles, from bundled metadata."""
        result: dict[str, list[str]] = {}
        for app in self.apps():
            for category in app.categories or ["Uncategorised"]:
                result.setdefault(category, []).append(f"{app.repo}/{app.role}")
        return dict(sorted(result.items()))
