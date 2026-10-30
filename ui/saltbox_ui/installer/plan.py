"""The install plan: every answer the wizard collects, and how it lands in
Saltbox's own files.

The plan is saved as JSON under the engine state directory so an install can
be resumed after a reboot or a dropped SSH session. Applying the plan writes
the same ``accounts.yml``, ``settings.yml``, ``adv_settings.yml``,
``providers.yml``, ``backup_config.yml`` and inventory a person would edit by
hand, so nothing about the resulting install is special.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from ..config import ConfigService, Inventory
from ..yamlio import set_path

PHASES = ("collect", "preinstall", "storage", "install", "done")
PROFILES = ("saltbox", "mediabox", "feederbox", "core", "custom")
DNS_MODES = ("cloudflare_token", "cloudflare_global", "provider", "manual")
STORAGE_MODES = ("local", "existing", "create")
TEMPLATES = ("google", "dropbox", "sftp", "nfs")

# Traefik DNS challenge providers Saltbox ships credentials for, from providers.yml.default.
PROVIDER_FIELDS: dict[str, list[str]] = {
    "cloudns": ["client_id", "email", "password"],
    "duckdns": ["token"],
    "dynu": ["api_key"],
    "godaddy": ["api_key", "api_secret"],
    "hetzner": ["api_key"],
    "linode": ["token"],
    "namecheap": ["api_key", "api_user"],
    "namedotcom": ["api_token", "server", "username"],
    "netcup": ["api_key", "api_password", "customer_number"],
    "porkbun": ["api_key", "secret_key"],
    "powerdns": ["api_key", "api_url"],
}


@dataclass
class Remote:
    remote: str
    template: str = "google"
    mount: bool = True
    union: bool = True
    upload: bool = False
    upload_from: str = "/mnt/local/Media"
    enable_refresh: bool = False
    vfs_cache_enabled: bool = False
    vfs_cache_max_age: str = "504h"
    vfs_cache_size: str = "50G"

    def as_settings(self) -> dict[str, Any]:
        return {
            "remote": self.remote,
            "settings": {
                "enable_refresh": _yn(self.enable_refresh),
                "mount": _yn(self.mount),
                "template": self.template,
                "union": _yn(self.union),
                "upload": _yn(self.upload),
                "upload_from": self.upload_from,
                "vfs_cache": {
                    "enabled": _yn(self.vfs_cache_enabled),
                    "max_age": self.vfs_cache_max_age,
                    "size": self.vfs_cache_size,
                },
            },
        }


@dataclass
class InstallPlan:
    phase: str = "collect"
    # Account and domain
    user_name: str = "seed"
    user_pass: str = ""
    domain: str = ""
    email: str = ""
    ssh_key: str = ""
    # DNS and certificates
    dns_mode: str = "cloudflare_token"
    cloudflare_token: str = ""
    cloudflare_api: str = ""
    cloudflare_email: str = ""
    provider: str = ""
    provider_credentials: dict[str, str] = field(default_factory=dict)
    dns_proxied: bool = False
    dns_ipv6: bool = False
    http_validation: bool = False
    zerossl: bool = False
    # Docker Hub
    dockerhub_user: str = ""
    dockerhub_token: str = ""
    # Storage
    storage_mode: str = "local"
    remotes: list[Remote] = field(default_factory=list)
    # Apps
    profile: str = "saltbox"
    media_servers: list[str] = field(default_factory=lambda: ["plex"])
    download_clients: list[str] = field(default_factory=lambda: ["qbittorrent", "sabnzbd"])
    download_indexers: list[str] = field(default_factory=lambda: ["jackett", "nzbhydra2"])
    extra_apps: list[str] = field(default_factory=list)
    sandbox_apps: list[str] = field(default_factory=list)
    authelia_master: bool = True
    authelia_subdomain: str = "login"
    # Advanced
    timezone: str = "auto"
    shell: str = "bash"
    intel_gpu: bool = True
    hsts: bool = False
    downloads: str = "/mnt/unionfs/downloads"
    transcodes: str = "/mnt/local/transcodes"
    # Backup
    backup_local: bool = True
    backup_rclone: bool = False
    backup_rclone_destination: str = "google:/Backups/Saltbox"
    backup_cron: str = "weekly"
    # Progress
    jobs: dict[str, str] = field(default_factory=dict)
    preinstall_started_at: float | None = None
    notes: list[str] = field(default_factory=list)

    # -- persistence -----------------------------------------------------------
    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.as_dict(), indent=1), encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> InstallPlan:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstallPlan:
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        clean["remotes"] = [
            Remote(**r) if isinstance(r, dict) else r for r in clean.get("remotes", [])
        ]
        return cls(**clean)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def redacted(self) -> dict[str, Any]:
        data = self.as_dict()
        for key in ("user_pass", "cloudflare_token", "cloudflare_api", "dockerhub_token"):
            if data.get(key):
                data[key] = "•" * 8
        data["provider_credentials"] = {k: "•" * 8 for k in self.provider_credentials}
        return data

    # -- derived ------------------------------------------------------------
    @property
    def uses_cloudflare(self) -> bool:
        return self.dns_mode in {"cloudflare_token", "cloudflare_global"}

    @property
    def rclone_enabled(self) -> bool:
        return self.storage_mode in {"existing", "create"} and bool(self.remotes)

    def install_tags(self) -> list[str]:
        """Tags for the main install run, after preinstall."""
        main = {"saltbox", "mediabox", "feederbox"}
        tags = [self.profile] if self.profile in main else ["core"]
        tags += [a for a in self.extra_apps if a not in tags]
        tags += [f"sandbox-{a}" for a in self.sandbox_apps]
        return tags

    def summary(self) -> list[tuple[str, str]]:
        storage = {
            "local": "local disk only (rclone disabled)",
            "existing": f"existing rclone config, {len(self.remotes)} remote(s)",
            "create": "new rclone remotes: "
            + (", ".join(r.remote for r in self.remotes) or "none yet"),
        }[self.storage_mode]
        dns = {
            "cloudflare_token": "Cloudflare, scoped token",
            "cloudflare_global": "Cloudflare, global API key",
            "provider": f"DNS challenge via {self.provider or '?'}",
            "manual": "manual DNS, HTTP certificate validation",
        }[self.dns_mode]
        return [
            ("User", self.user_name),
            ("Domain", self.domain),
            ("Email", self.email),
            ("DNS", dns),
            ("Storage", storage),
            ("Install", " ".join(self.install_tags())),
            ("Media servers", ", ".join(self.media_servers)),
            ("Download clients", ", ".join(self.download_clients)),
            ("Indexers", ", ".join(self.download_indexers)),
            ("Timezone", self.timezone),
        ]

    # -- apply --------------------------------------------------------------
    def apply(
        self, config: ConfigService, inventory: Inventory, catalog_profiles: dict
    ) -> list[str]:
        """Write the plan into Saltbox's config files. Returns the files touched."""
        touched: list[str] = []

        accounts = config.load("accounts")
        set_path(accounts, "user.name", self.user_name)
        set_path(accounts, "user.pass", self.user_pass)
        set_path(accounts, "user.domain", self.domain)
        set_path(accounts, "user.email", self.email)
        set_path(accounts, "user.ssh_key", self.ssh_key or None)
        set_path(accounts, "cloudflare.api", self.cloudflare_api or None)
        set_path(accounts, "cloudflare.email", self.cloudflare_email or None)
        set_path(accounts, "cloudflare.scoped_token", self.cloudflare_token or None)
        if not self.uses_cloudflare:
            set_path(accounts, "cloudflare.api", None)
            set_path(accounts, "cloudflare.email", None)
            set_path(accounts, "cloudflare.scoped_token", None)
        set_path(accounts, "dockerhub.user", self.dockerhub_user or None)
        set_path(accounts, "dockerhub.token", self.dockerhub_token or None)
        config.save("accounts", accounts)
        touched.append("accounts.yml")

        settings = config.load("settings")
        set_path(settings, "authelia.master", _yn(self.authelia_master))
        set_path(settings, "authelia.subdomain", self.authelia_subdomain)
        set_path(settings, "downloads", self.downloads)
        set_path(settings, "transcodes", self.transcodes)
        set_path(settings, "shell", self.shell)
        set_path(settings, "rclone.enabled", _yn(self.rclone_enabled))
        if self.rclone_enabled:
            set_path(settings, "rclone.remotes", _seq([r.as_settings() for r in self.remotes]))
        elif "remotes" in settings.get("rclone", {}):
            del settings["rclone"]["remotes"]
        config.save("settings", settings)
        touched.append("settings.yml")

        adv = config.load("adv_settings")
        set_path(adv, "dns.ipv4", "yes")
        set_path(adv, "dns.ipv6", _yn(self.dns_ipv6))
        set_path(adv, "dns.proxied", _yn(self.dns_proxied))
        set_path(adv, "gpu.intel", _yn(self.intel_gpu))
        set_path(adv, "system.timezone", self.timezone)
        set_path(adv, "traefik.hsts", _yn(self.hsts))
        set_path(adv, "traefik.cert.zerossl", _yn(self.zerossl))
        provider = "cloudflare"
        http_validation = self.http_validation
        if self.dns_mode == "provider":
            provider = self.provider
        elif self.dns_mode == "manual":
            http_validation = True
        set_path(adv, "traefik.provider", provider)
        set_path(adv, "traefik.cert.http_validation", _yn(http_validation))
        config.save("adv_settings", adv)
        touched.append("adv_settings.yml")

        if self.dns_mode == "provider" and self.provider:
            providers = config.load("providers")
            for key, value in self.provider_credentials.items():
                set_path(providers, f"{self.provider}.{key}", value or None)
            config.save("providers", providers)
            touched.append("providers.yml")

        backup = config.load("backup_config")
        set_path(backup, "backup.cron.cron_time", self.backup_cron)
        set_path(backup, "backup.local.enable", bool(self.backup_local))
        set_path(backup, "backup.rclone.enable", bool(self.backup_rclone and self.rclone_enabled))
        if self.backup_rclone and self.rclone_enabled:
            set_path(backup, "backup.rclone.destination", self.backup_rclone_destination)
            set_path(backup, "backup.rclone.template", self.remotes[0].template)
        config.save("backup_config", backup)
        touched.append("backup_config.yml")

        overrides: dict[str, Any] = {}
        if self.media_servers != catalog_profiles.get("media_servers_enabled", ["plex"]):
            overrides["media_servers_enabled"] = list(self.media_servers)
        if self.download_clients != catalog_profiles.get("download_clients_enabled"):
            overrides["download_clients_enabled"] = list(self.download_clients)
        if self.download_indexers != catalog_profiles.get("download_indexers_enabled"):
            overrides["download_indexers_enabled"] = list(self.download_indexers)
        if self.sandbox_apps:
            overrides["sandbox_roles"] = list(self.sandbox_apps)
        if overrides:
            inventory.update(overrides)
            touched.append("inventories/host_vars/localhost.yml")
        return touched


def _yn(value: bool) -> str:
    return "yes" if value else "no"


def _seq(items: list[dict[str, Any]]) -> CommentedSeq:
    seq = CommentedSeq()
    for item in items:
        seq.append(_map(item))
    return seq


def _map(data: dict[str, Any]) -> CommentedMap:
    result = CommentedMap()
    for key, value in data.items():
        result[key] = _map(value) if isinstance(value, dict) else value
    return result
