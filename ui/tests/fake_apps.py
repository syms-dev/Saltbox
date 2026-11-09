"""In-memory stand-ins for the apps' HTTP APIs, routed by host name.

Each fake checks credentials the way the real app does and keeps what was
created, so tests can assert on the exact requests the setup step made.
"""

from __future__ import annotations

import copy
import itertools
import json
import urllib.parse
from typing import Any

from saltbox_ui.appsetup.http import Response, SetupError

CATEGORY_FIELD = {"sonarr": "tvCategory", "radarr": "movieCategory", "lidarr": "musicCategory"}


def _json(status: int, data: Any) -> Response:
    return Response(status, json.dumps(data).encode(), {"content-type": "application/json"})


def _fields(*names: str) -> list[dict[str, Any]]:
    return [{"name": name, "value": None} for name in names]


class FakeArr:
    def __init__(self, role: str, api_key: str):
        self.role = role
        self.api_key = api_key
        self.version = "v3" if role in ("sonarr", "radarr") else "v1"
        self.rootfolders: list[dict[str, Any]] = []
        self.downloadclients: list[dict[str, Any]] = []
        self.notifications: list[dict[str, Any]] = []
        self.applications: list[dict[str, Any]] = []
        self.ids = itertools.count(1)

    def schemas(self, resource: str) -> list[dict[str, Any]]:
        if resource == "downloadclient":
            category = CATEGORY_FIELD.get(self.role, "category")
            imported = category.replace("Category", "ImportedCategory")
            return [
                {
                    "implementation": "QBittorrent",
                    "configContract": "QBittorrentSettings",
                    "protocol": "torrent",
                    "fields": _fields(
                        "host",
                        "port",
                        "useSsl",
                        "urlBase",
                        "username",
                        "password",
                        category,
                        imported,
                    ),
                },
                {
                    "implementation": "Sabnzbd",
                    "configContract": "SabnzbdSettings",
                    "protocol": "usenet",
                    "fields": _fields("host", "port", "useSsl", "apiKey", category),
                },
            ]
        if resource == "notification":
            return [
                {
                    "implementation": "Webhook",
                    "configContract": "WebhookSettings",
                    "onGrab": False,
                    "onDownload": False,
                    "onUpgrade": False,
                    "onRename": False,
                    "onSeriesDelete": False,
                    "onEpisodeFileDelete": False,
                    "onHealthIssue": False,
                    "supportsOnGrab": True,
                    "supportsOnDownload": True,
                    "supportsOnUpgrade": True,
                    "supportsOnRename": True,
                    "supportsOnSeriesDelete": True,
                    "supportsOnEpisodeFileDelete": True,
                    "supportsOnHealthIssue": True,
                    "fields": _fields("url", "method", "username", "password"),
                }
            ]
        if resource == "applications":
            return [
                {
                    "implementation": name,
                    "configContract": f"{name}Settings",
                    "syncLevel": "addOnly",
                    "fields": _fields("prowlarrUrl", "baseUrl", "apiKey", "syncCategories"),
                }
                for name in ("Sonarr", "Radarr", "Lidarr")
            ]
        return []

    def handle(self, method: str, path: str, headers: dict[str, str], body: bytes | None):
        if headers.get("X-Api-Key") != self.api_key:
            return _json(401, {"message": "Unauthorized"})
        prefix = f"/api/{self.version}/"
        if not path.startswith(prefix):
            return _json(404, {"message": "Not Found"})
        resource = path[len(prefix) :].split("?", 1)[0]
        stores = {
            "rootfolder": self.rootfolders,
            "downloadclient": self.downloadclients,
            "notification": self.notifications,
            "applications": self.applications,
        }
        if method == "GET" and resource.endswith("/schema"):
            return _json(200, self.schemas(resource.removesuffix("/schema")))
        if method == "GET" and resource == "qualityprofile":
            return _json(200, [{"id": 4, "name": "Any"}])
        if method == "GET" and resource == "metadataprofile":
            return _json(200, [{"id": 7, "name": "Standard"}])
        if resource in stores:
            store = stores[resource]
            if method == "GET":
                return _json(200, store)
            if method == "POST":
                item = json.loads(body or b"{}")
                if resource == "rootfolder" and self.role == "lidarr":
                    for key in ("name", "defaultQualityProfileId", "defaultMetadataProfileId"):
                        if key not in item:
                            return _json(400, [{"errorMessage": f"'{key}' must not be empty"}])
                if resource != "rootfolder":
                    for entry in item.get("fields", []):
                        if entry["name"] in ("host", "url", "baseUrl") and not entry["value"]:
                            return _json(400, [{"errorMessage": f"{entry['name']} is required"}])
                item["id"] = next(self.ids)
                store.append(item)
                return _json(201, item)
        return _json(404, {"message": "Not Found"})


class FakeQbit:
    def __init__(self, user: str, password: str):
        self.user = user
        self.password = password
        self.preferences: dict[str, Any] = {"save_path": "/downloads/", "temp_path_enabled": False}
        self.logins = 0

    def handle(self, method: str, path: str, headers: dict[str, str], body: bytes | None):
        if path == "/api/v2/auth/login" and method == "POST":
            form = dict(urllib.parse.parse_qsl((body or b"").decode()))
            if form.get("username") == self.user and form.get("password") == self.password:
                self.logins += 1
                return Response(200, b"Ok.", {"set-cookie": "SID=s3cr3t; HttpOnly; path=/"})
            return Response(200, b"Fails.", {})
        if headers.get("Cookie") != "SID=s3cr3t":
            return Response(403, b"Forbidden", {})
        if path == "/api/v2/app/preferences" and method == "GET":
            return _json(200, self.preferences)
        if path == "/api/v2/app/setPreferences" and method == "POST":
            form = dict(urllib.parse.parse_qsl((body or b"").decode()))
            self.preferences.update(json.loads(form["json"]))
            return Response(200, b"", {})
        return Response(404, b"Not Found", {})


class FakePlex:
    def __init__(self, token: str):
        self.token = token
        self.sections: list[dict[str, Any]] = []
        self.refreshed: list[str] = []

    def handle(self, method: str, path: str, headers: dict[str, str], body: bytes | None):
        if headers.get("X-Plex-Token") != self.token:
            return Response(401, b"Unauthorized", {})
        url = urllib.parse.urlsplit(path)
        if url.path == "/library/sections" and method == "GET":
            return _json(200, {"MediaContainer": {"Directory": copy.deepcopy(self.sections)}})
        if url.path == "/library/sections" and method == "POST":
            query = dict(urllib.parse.parse_qsl(url.query))
            key = str(len(self.sections) + 1)
            self.sections.append(
                {
                    "key": key,
                    "title": query["name"],
                    "type": query["type"],
                    "agent": query["agent"],
                    "scanner": query["scanner"],
                    "Location": [{"id": int(key), "path": query["location"]}],
                }
            )
            return _json(200, {"MediaContainer": {}})
        if url.path.endswith("/refresh") and method == "GET":
            self.refreshed.append(url.path.split("/")[3])
            return Response(200, b"", {})
        return Response(404, b"Not Found", {})


class FakeNetwork:
    """A transport that routes ``http://name:port`` to the registered fake."""

    def __init__(self) -> None:
        self.apps: dict[str, Any] = {}
        self.down: set[str] = set()
        self.calls: list[tuple[str, str]] = []

    def add(self, host: str, app: Any) -> Any:
        self.apps[host] = app
        return app

    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes | None):
        parts = urllib.parse.urlsplit(url)
        self.calls.append((method, url))
        if parts.hostname in self.down or parts.hostname not in self.apps:
            raise SetupError(f"cannot reach {parts.netloc}: connection refused")
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        return self.apps[parts.hostname].handle(method, path, headers, body)
