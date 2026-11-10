"""The connections between apps that the Saltbox docs ask people to make by hand.

Every task checks the app's current state before changing anything and adds
only what is missing, so running setup again is always safe. The values come
from the Saltbox app docs: root folders under ``/mnt/unionfs/Media``,
qBittorrent with a per-app category, Autoscan webhooks with Import, Upgrade,
Rename and delete events, Prowlarr syncing to each app, and Plex libraries on
the same paths.

Steps that need a browser sign-in (Seerr) or have no stable API (Bazarr) are
reported as manual, with the exact values to enter.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .discover import API_VERSION, ARR_ROLES, Discovery, Service
from .http import Client, Response, SetupError, Transport

MEDIA_ROOT = "/mnt/unionfs/Media"
ROOT_FOLDERS = {"sonarr": "TV", "radarr": "Movies", "lidarr": "Music"}
TORRENTS = "/mnt/unionfs/downloads/torrents/qbittorrent"
QBIT_PREFERENCES = {
    "save_path": f"{TORRENTS}/completed/",
    "temp_path_enabled": True,
    "temp_path": f"{TORRENTS}/incoming/",
    "export_dir": f"{TORRENTS}/torrents/",
    "export_dir_fin": f"{TORRENTS}/torrents/",
}
# Autoscan wants events that point at one file on disk; everything else stays off.
AUTOSCAN_EVENTS = {
    "onDownload",
    "onReleaseImport",
    "onUpgrade",
    "onRename",
    "onSeriesDelete",
    "onEpisodeFileDelete",
    "onEpisodeFileDeleteForUpgrade",
    "onMovieDelete",
    "onMovieFileDelete",
    "onMovieFileDeleteForUpgrade",
    "onArtistDelete",
    "onTrackFileDelete",
    "onTrackFileDeleteForUpgrade",
}
PLEX_LIBRARIES = {
    "radarr": ("Movies", "movie", "tv.plex.agents.movie", "Plex Movie"),
    "sonarr": ("TV Shows", "show", "tv.plex.agents.series", "Plex TV Series"),
    "lidarr": ("Music", "artist", "tv.plex.agents.music", "Plex Music"),
}

STATUSES = ("done", "todo", "manual", "skip", "error")


@dataclass
class Task:
    id: str
    app: str
    title: str
    check: Callable[[], tuple[str, str]]
    apply: Callable[[], None] | None = None
    status: str = "todo"
    detail: str = ""

    def refresh(self) -> Task:
        try:
            self.status, self.detail = self.check()
        except SetupError as error:
            self.status, self.detail = "error", str(error)
        return self

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "app": self.app,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "automatic": "yes" if self.apply else "no",
        }


@dataclass
class SetupContext:
    found: Discovery
    transport: Transport | None = None
    ensure_dir: Callable[[Path], None] | None = None
    _qbit_cookie: str = field(default="", repr=False)
    _sab_servers: dict[str, int] = field(default_factory=dict, repr=False)

    # -- clients -----------------------------------------------------------
    def arr(self, service: Service) -> Client:
        version = API_VERSION[service.role]
        return Client(
            f"{service.host_url}/api/{version}",
            headers={"X-Api-Key": service.api_key},
            transport=self.transport,
            name=service.name,
        )

    def plex(self, service: Service) -> Client:
        return Client(
            service.host_url,
            headers={"X-Plex-Token": self.found.plex_token},
            transport=self.transport,
            name=service.name,
        )

    def qbit(self, service: Service) -> Client:
        client = Client(service.host_url, transport=self.transport, name=service.name)
        if not self._qbit_cookie:
            response = client.request(
                "POST",
                "/api/v2/auth/login",
                form={"username": self.found.user, "password": self.found.password},
                headers={"Referer": service.host_url},
                ok=(200, 401, 403),
            )
            if response.status == 403:
                raise SetupError(
                    f"{service.name}: this server's address is banned after too many failed "
                    "logins; restart qBittorrent to lift the ban"
                )
            cookie = session_cookie(response.headers.get("set-cookie", ""))
            if response.status == 401 or "Ok" not in response.text or not cookie:
                raise SetupError(
                    f"{service.name}: rejected user '{self.found.user}' with the password from "
                    "accounts.yml, so the other apps can't log in either. Its login was set "
                    "before Saltbox could, or changed in its web UI"
                )
            self._qbit_cookie = cookie
        client.headers["Cookie"] = self._qbit_cookie
        client.headers["Referer"] = service.host_url
        return client

    def sab(self, service: Service) -> Client:
        return SabClient(
            service.host_url, service.api_key, transport=self.transport, name=service.name
        )

    def sab_servers(self, service: Service) -> int:
        """How many Usenet servers SABnzbd has; categories are pointless without one."""
        if service.name not in self._sab_servers:
            data = self.sab(service).get(
                "/api", params={"mode": "get_config", "section": "servers", "output": "json"}
            )
            servers = ((data or {}).get("config") or {}).get("servers") or []
            self._sab_servers[service.name] = len(servers)
        return self._sab_servers[service.name]

    def make_dir(self, path: str) -> None:
        if self.ensure_dir is not None:
            self.ensure_dir(Path(path))


class SabClient(Client):
    """SABnzbd's API takes the key as a query parameter on every call."""

    def __init__(self, base_url: str, api_key: str, **kwargs: Any):
        super().__init__(base_url, **kwargs)
        self.api_key = api_key

    def request(self, method: str, path: str, **kwargs: Any) -> Response:
        params = {**(kwargs.pop("params", None) or {}), "apikey": self.api_key}
        response = super().request(method, path, params=params, **kwargs)
        data = response.json()
        if isinstance(data, dict) and data.get("status") is False:
            raise SetupError(f"{self.name}: {data.get('error') or 'request refused'}")
        return response


# -- helpers -----------------------------------------------------------------
def session_cookie(header: str) -> str:
    """The qBittorrent session cookie (``SID`` or a renamed one) from Set-Cookie lines."""
    pairs = [line.split(";", 1)[0].strip() for line in header.splitlines() if "=" in line]
    for pair in pairs:
        if "sid" in pair.split("=", 1)[0].lower():
            return pair
    return pairs[0] if pairs else ""


def schema_item(client: Client, resource: str, implementation: str) -> dict[str, Any]:
    for item in client.get(f"/{resource}/schema") or []:
        if str(item.get("implementation", "")).lower() == implementation.lower():
            return item
    raise SetupError(f"{client.name}: no '{implementation}' option in {resource}")


def set_fields(item: dict[str, Any], values: dict[str, Any]) -> None:
    for entry in item.get("fields", []):
        if entry.get("name") in values:
            entry["value"] = values[entry["name"]]


def field_value(item: dict[str, Any], name: str) -> Any:
    for entry in item.get("fields", []):
        if entry.get("name") == name:
            return entry.get("value")
    return None


def category_fields(item: dict[str, Any], category: str) -> dict[str, str]:
    """Every '...Category' field except the post-import ones, set to ``category``."""
    return {
        entry["name"]: category
        for entry in item.get("fields", [])
        if str(entry.get("name", "")).lower().endswith("category")
        and "imported" not in str(entry.get("name", "")).lower()
    }


def same_path(a: str, b: str) -> bool:
    return a.rstrip("/") == b.rstrip("/")


# -- tasks -------------------------------------------------------------------
def qbit_folders_task(ctx: SetupContext, qbit: Service) -> Task:
    def check() -> tuple[str, str]:
        prefs = ctx.qbit(qbit).get("/api/v2/app/preferences") or {}
        if same_path(str(prefs.get("save_path", "")), QBIT_PREFERENCES["save_path"]):
            return "done", f"saves to {QBIT_PREFERENCES['save_path']}"
        return "todo", f"currently saves to {prefs.get('save_path') or 'the image default'}"

    def apply() -> None:
        for sub in ("completed", "incoming", "torrents"):
            ctx.make_dir(f"{TORRENTS}/{sub}")
        ctx.qbit(qbit).request(
            "POST", "/api/v2/app/setPreferences", form={"json": json.dumps(QBIT_PREFERENCES)}
        )

    return Task(f"{qbit.name}:folders", "qBittorrent", "Download folders", check, apply)


def root_folder_task(ctx: SetupContext, arr: Service) -> Task:
    folder = f"{MEDIA_ROOT}/{ROOT_FOLDERS[arr.role]}"
    title = "Root folder"

    def check() -> tuple[str, str]:
        if arr.name != arr.role:
            return "manual", f"pick a root folder for {arr.name} yourself"
        folders = ctx.arr(arr).get("/rootfolder") or []
        if any(same_path(str(f.get("path", "")), folder) for f in folders):
            return "done", folder
        return "todo", f"will add {folder}"

    def apply() -> None:
        ctx.make_dir(folder)
        client = ctx.arr(arr)
        body: dict[str, Any] = {"path": folder}
        if arr.role == "lidarr":
            quality = client.get("/qualityprofile") or []
            metadata = client.get("/metadataprofile") or []
            if not quality or not metadata:
                raise SetupError(f"{arr.name}: no quality or metadata profile to use")
            body.update(
                name=ROOT_FOLDERS["lidarr"],
                defaultQualityProfileId=quality[0]["id"],
                defaultMetadataProfileId=metadata[0]["id"],
                defaultMonitorOption="all",
                defaultNewItemMonitorOption="all",
                defaultTags=[],
            )
        client.post("/rootfolder", body)

    return Task(f"{arr.name}:rootfolder", arr.role.capitalize(), title, check, apply)


def download_client_task(
    ctx: SetupContext,
    app: Service,
    client_service: Service,
    *,
    implementation: str,
    label: str,
    category: str,
    values: dict[str, Any],
    requires: Callable[[], tuple[str, str] | None] | None = None,
) -> Task:
    def check() -> tuple[str, str]:
        blocked = requires() if requires else None
        if blocked:
            return blocked
        existing = ctx.arr(app).get("/downloadclient") or []
        for item in existing:
            if str(item.get("implementation", "")).lower() == implementation.lower():
                return "done", f"{item.get('name', label)} is set up"
        return "todo", f"will add {label} with category '{category}'"

    def apply() -> None:
        client = ctx.arr(app)
        item = schema_item(client, "downloadclient", implementation)
        set_fields(item, {**values, **category_fields(item, category)})
        item.update(name=label, enable=True, priority=1, tags=[])
        client.post("/downloadclient", item)

    return Task(
        f"{app.name}:{client_service.name}",
        app.role.capitalize(),
        f"{label} downloads",
        check,
        apply,
    )


def autoscan_task(ctx: SetupContext, arr: Service, autoscan: Service) -> Task:
    url = f"{autoscan.url}/triggers/{arr.name}"

    def check() -> tuple[str, str]:
        for item in ctx.arr(arr).get("/notification") or []:
            if str(item.get("implementation", "")).lower() == "webhook" and "autoscan" in str(
                field_value(item, "url") or ""
            ):
                return "done", "Autoscan is notified of new files"
        return "todo", f"will add a webhook to {url}"

    def apply() -> None:
        client = ctx.arr(arr)
        item = schema_item(client, "notification", "Webhook")
        set_fields(
            item,
            {"url": url, "method": 1, "username": ctx.found.user, "password": ctx.found.password},
        )
        for key, value in list(item.items()):
            if key.startswith("on") and isinstance(value, bool):
                supported = item.get("supports" + key[0].upper() + key[1:], True)
                item[key] = key in AUTOSCAN_EVENTS and bool(supported)
        item.update(name="Autoscan", tags=[])
        client.post("/notification", item)

    return Task(f"{arr.name}:autoscan", arr.role.capitalize(), "Autoscan webhook", check, apply)


def prowlarr_app_task(ctx: SetupContext, prowlarr: Service, arr: Service) -> Task:
    implementation = arr.role.capitalize()

    def check() -> tuple[str, str]:
        for item in ctx.arr(prowlarr).get("/applications") or []:
            if str(item.get("implementation", "")).lower() == arr.role and same_path(
                str(field_value(item, "baseUrl") or ""), arr.url
            ):
                return "done", f"indexers sync to {arr.name}"
        return "todo", f"will sync indexers to {arr.name}"

    def apply() -> None:
        if not arr.api_key:
            raise SetupError(f"{arr.name}: API key not found in its config.xml")
        client = ctx.arr(prowlarr)
        item = schema_item(client, "applications", implementation)
        set_fields(item, {"prowlarrUrl": prowlarr.url, "baseUrl": arr.url, "apiKey": arr.api_key})
        item.update(name=arr.name.capitalize(), syncLevel="fullSync", tags=[])
        client.post("/applications", item)

    return Task(
        f"{prowlarr.name}:{arr.name}", "Prowlarr", f"Sync to {arr.name.capitalize()}", check, apply
    )


def plex_library_task(ctx: SetupContext, plex: Service, role: str) -> Task:
    title_name, kind, agent, scanner = PLEX_LIBRARIES[role]
    folder = f"{MEDIA_ROOT}/{ROOT_FOLDERS[role]}"

    def sections() -> list[dict[str, Any]]:
        data = ctx.plex(plex).get("/library/sections") or {}
        return list((data.get("MediaContainer") or {}).get("Directory") or [])

    def check() -> tuple[str, str]:
        if not ctx.found.plex_token:
            return "manual", "no Plex token found; add the library in Plex yourself"
        for section in sections():
            for location in section.get("Location") or []:
                if same_path(str(location.get("path", "")), folder):
                    return "done", f"'{section.get('title')}' uses {folder}"
        return "todo", f"will add '{title_name}' on {folder} and scan it"

    def apply() -> None:
        client = ctx.plex(plex)
        client.request(
            "POST",
            "/library/sections",
            params={
                "name": title_name,
                "type": kind,
                "agent": agent,
                "scanner": scanner,
                "language": "en-US",
                "location": folder,
            },
        )
        # Autoscan only updates libraries that have been scanned once.
        for section in sections():
            if any(
                same_path(str(loc.get("path", "")), folder) for loc in section.get("Location") or []
            ):
                client.request("GET", f"/library/sections/{section.get('key')}/refresh")

    return Task(f"{plex.name}:{role}", "Plex", f"{title_name} library", check, apply)


def sab_blocker(ctx: SetupContext, sab: Service) -> tuple[str, str] | None:
    if ctx.sab_servers(sab) == 0:
        return "skip", "skipped: SABnzbd has no Usenet server yet"
    return None


def sab_categories_task(ctx: SetupContext, sab: Service, categories: list[str]) -> Task:
    def missing() -> list[str]:
        data = ctx.sab(sab).get("/api", params={"mode": "get_cats", "output": "json"}) or {}
        have = {str(c).lower() for c in data.get("categories") or []}
        return [c for c in categories if c.lower() not in have]

    def check() -> tuple[str, str]:
        if sab_blocker(ctx, sab):
            return (
                "skip",
                "SABnzbd has no Usenet server. Add your provider in SABnzbd and run this "
                "again, or ignore it if you don't use Usenet",
            )
        absent = missing()
        if not absent:
            return "done", f"categories {', '.join(categories)} exist"
        return "todo", f"will add categories {', '.join(absent)}"

    def apply() -> None:
        client = ctx.sab(sab)
        for category in missing():
            client.get(
                "/api",
                params={
                    "mode": "set_config",
                    "section": "categories",
                    "keyword": category,
                    "name": category,
                    "dir": category,
                    "output": "json",
                },
            )

    return Task(f"{sab.name}:categories", "SABnzbd", "Categories", check, apply)


def manual_task(task_id: str, app: str, title: str, text: str) -> Task:
    return Task(task_id, app, title, lambda: ("manual", text))


def bazarr_text(found: Discovery) -> str:
    lines = ["In Bazarr: Settings, then Sonarr and Radarr. Enable each and enter:"]
    for role in ("sonarr", "radarr"):
        service = found.first(role)
        if service:
            lines.append(
                f"{role.capitalize()}: address {service.name}, port {service.port}, "
                f"API key {service.api_key or '(see its Settings, General)'}"
            )
    lines.append("Then pick your subtitle languages and providers.")
    return "\n".join(lines)


def seerr_text(found: Discovery) -> str:
    lines = [
        "Open Seerr in your browser and sign in with Plex. When it asks for servers, enter:",
    ]
    plex = found.first("plex")
    if plex:
        lines.append(f"Plex: {plex.name}, port {plex.port}, no SSL; then sync and pick libraries")
    for role in ("radarr", "sonarr"):
        service = found.first(role)
        if service:
            folder = f"{MEDIA_ROOT}/{ROOT_FOLDERS[role]}"
            lines.append(
                f"{role.capitalize()}: {service.name}, port {service.port}, API key "
                f"{service.api_key or '(see its Settings, General)'}, root folder {folder}"
            )
    return "\n".join(lines)


# -- plan ----------------------------------------------------------------------
def build_tasks(ctx: SetupContext) -> list[Task]:
    found = ctx.found
    tasks: list[Task] = []
    qbit = found.first("qbittorrent")
    sab = found.first("sabnzbd")
    autoscan = found.first("autoscan")
    prowlarr = found.first("prowlarr")
    plex = found.first("plex")

    if qbit:
        tasks.append(qbit_folders_task(ctx, qbit))
    if sab and sab.api_key:
        categories = [arr.name for role in ARR_ROLES for arr in found.installed(role)]
        if categories:
            tasks.append(sab_categories_task(ctx, sab, categories))
    for role in ("sonarr", "radarr", "lidarr"):
        for arr in found.installed(role):
            if not arr.api_key:
                tasks.append(
                    manual_task(
                        f"{arr.name}:apikey",
                        role.capitalize(),
                        "API key",
                        f"no API key in /opt/{arr.name}/config.xml yet; open {arr.name} once "
                        "so it creates one, then check again",
                    )
                )
                continue
            tasks.append(root_folder_task(ctx, arr))
            if qbit:
                tasks.append(
                    download_client_task(
                        ctx,
                        arr,
                        qbit,
                        implementation="QBittorrent",
                        label="qBittorrent",
                        category=arr.name,
                        values={
                            "host": qbit.name,
                            "port": qbit.port,
                            "useSsl": False,
                            "username": found.user,
                            "password": found.password,
                        },
                    )
                )
            if sab and sab.api_key:
                tasks.append(
                    download_client_task(
                        ctx,
                        arr,
                        sab,
                        implementation="Sabnzbd",
                        label="SABnzbd",
                        category=arr.name,
                        values={
                            "host": sab.name,
                            "port": sab.port,
                            "useSsl": False,
                            "apiKey": sab.api_key,
                        },
                        requires=lambda sab=sab: sab_blocker(ctx, sab),
                    )
                )
            if autoscan:
                tasks.append(autoscan_task(ctx, arr, autoscan))
    if prowlarr and prowlarr.api_key:
        for role in ("sonarr", "radarr", "lidarr"):
            for arr in found.installed(role):
                if arr.api_key:
                    tasks.append(prowlarr_app_task(ctx, prowlarr, arr))
        if qbit:
            tasks.append(
                download_client_task(
                    ctx,
                    prowlarr,
                    qbit,
                    implementation="QBittorrent",
                    label="qBittorrent",
                    category="prowlarr",
                    values={
                        "host": qbit.name,
                        "port": qbit.port,
                        "useSsl": False,
                        "username": found.user,
                        "password": found.password,
                    },
                )
            )
    if plex:
        for role in ("radarr", "sonarr", "lidarr"):
            if found.installed(role):
                tasks.append(plex_library_task(ctx, plex, role))
    if found.first("bazarr"):
        tasks.append(manual_task("bazarr", "Bazarr", "Link apps", bazarr_text(found)))
    if found.first("seerr"):
        tasks.append(manual_task("seerr", "Seerr", "First run", seerr_text(found)))
    return tasks


def check_all(tasks: list[Task]) -> list[Task]:
    return [task.refresh() for task in tasks]


def apply_all(tasks: list[Task], on_task: Callable[[Task], None] | None = None) -> list[Task]:
    """Apply every task still to do, in order, then re-check it."""
    for task in tasks:
        task.refresh()
        if task.status == "todo" and task.apply is not None:
            try:
                task.apply()
            except SetupError as error:
                task.status, task.detail = "error", str(error)
            else:
                task.refresh()
                if task.status == "todo":
                    task.status, task.detail = "error", f"still not set up: {task.detail}"
        if on_task:
            on_task(task)
    return tasks


def summarize(tasks: list[Task]) -> dict[str, int]:
    counts = dict.fromkeys(STATUSES, 0)
    for task in tasks:
        counts[task.status] = counts.get(task.status, 0) + 1
    return counts
