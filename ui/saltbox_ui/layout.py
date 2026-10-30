"""Filesystem layout of a Saltbox install.

Mirrors the constants in sb-go's ``layout`` package so the engine and the CLI
agree on where everything lives. Every path can be redirected with environment
variables so the engine can run against a plain git checkout for tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .yamlio import load_plain

DEFAULT_REPO = Path("/srv/git/saltbox")
DEFAULT_APPDATA = Path("/opt")
DEFAULT_SB_BINARY = Path("/usr/local/bin/sb")
DEFAULT_RCLONE_BINARY = Path("/usr/bin/rclone")
DOCKER_CONTROLLER_URL = "http://127.0.0.1:3377"

CONFIG_FILENAMES = {
    "accounts": "accounts.yml",
    "settings": "settings.yml",
    "adv_settings": "adv_settings.yml",
    "backup_config": "backup_config.yml",
    "providers": "providers.yml",
    "hetzner_vlan": "hetzner_vlan.yml",
    "motd": "motd.yml",
}


def appdata_from_inventory(inventory_path: Path) -> Path:
    """Return ``server_appdata_path`` from the inventory, or ``/opt``.

    Same rules as sb-go: a missing or unreadable file, a parse error, an
    unset value or a relative path all fall back to the default.
    """
    try:
        data = load_plain(inventory_path)
    except Exception:
        return DEFAULT_APPDATA
    if not isinstance(data, dict):
        return DEFAULT_APPDATA
    value = data.get("server_appdata_path")
    if not isinstance(value, str) or not value or not os.path.isabs(value):
        return DEFAULT_APPDATA
    return Path(os.path.normpath(value))


@dataclass(frozen=True)
class Layout:
    """Resolved paths for one Saltbox install."""

    repo: Path = DEFAULT_REPO
    appdata: Path = DEFAULT_APPDATA
    sb_binary: Path = DEFAULT_SB_BINARY
    rclone_binary: Path = DEFAULT_RCLONE_BINARY
    state_dir: Path = field(default_factory=lambda: Path("/var/lib/saltbox-ui"))

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> Layout:
        env = os.environ if environ is None else environ
        repo = Path(env.get("SALTBOX_REPO", DEFAULT_REPO))
        inventory = repo / "inventories" / "host_vars" / "localhost.yml"
        appdata_env = env.get("SALTBOX_APPDATA")
        appdata = Path(appdata_env) if appdata_env else appdata_from_inventory(inventory)
        return cls(
            repo=repo,
            appdata=appdata,
            sb_binary=Path(env.get("SB_BINARY", DEFAULT_SB_BINARY)),
            rclone_binary=Path(env.get("RCLONE_BINARY", DEFAULT_RCLONE_BINARY)),
            state_dir=Path(env.get("SALTBOX_UI_STATE", "/var/lib/saltbox-ui")),
        )

    # Repository files
    @property
    def playbook(self) -> Path:
        return self.repo / "saltbox.yml"

    @property
    def roles_dir(self) -> Path:
        return self.repo / "roles"

    @property
    def schema_dir(self) -> Path:
        return self.repo / "schema"

    @property
    def defaults_dir(self) -> Path:
        return self.repo / "defaults"

    @property
    def inventory(self) -> Path:
        return self.repo / "inventories" / "host_vars" / "localhost.yml"

    @property
    def group_vars(self) -> Path:
        return self.repo / "inventories" / "group_vars" / "all.yml"

    @property
    def cache_file(self) -> Path:
        return self.repo / "cache.json"

    @property
    def announcements(self) -> Path:
        return self.repo / "announcements.yml"

    @property
    def saltbox_fact(self) -> Path:
        return self.repo / "ansible_facts.d" / "saltbox.fact"

    def config_file(self, name: str) -> Path:
        return self.repo / CONFIG_FILENAMES[name]

    def default_file(self, name: str) -> Path:
        return self.defaults_dir / f"{CONFIG_FILENAMES[name]}.default"

    # Appdata
    @property
    def facts_dir(self) -> Path:
        return self.appdata / "saltbox"

    @property
    def ports_file(self) -> Path:
        return self.facts_dir / "port-assignments.json"

    @property
    def sandbox_repo(self) -> Path:
        return self.appdata / "sandbox"

    @property
    def sandbox_playbook(self) -> Path:
        return self.sandbox_repo / "sandbox.yml"

    @property
    def saltbox_mod_repo(self) -> Path:
        return self.appdata / "saltbox_mod"

    # Engine state
    @property
    def jobs_dir(self) -> Path:
        return self.state_dir / "jobs"

    @property
    def lock_file(self) -> Path:
        return self.state_dir / "runner.lock"

    def as_dict(self) -> dict[str, str]:
        return {
            "repo": str(self.repo),
            "appdata": str(self.appdata),
            "sb_binary": str(self.sb_binary),
            "rclone_binary": str(self.rclone_binary),
            "state_dir": str(self.state_dir),
            "inventory": str(self.inventory),
            "facts_dir": str(self.facts_dir),
            "sandbox_repo": str(self.sandbox_repo),
        }
