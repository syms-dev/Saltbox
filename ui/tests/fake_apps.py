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
from saltbox_ui.appsetup.tasks import ARR_MEDIA_MANAGEMENT, ARR_NAMING, PLEX_PREFERENCES

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
        self.config = self.stock_config(role)
        self.puts: list[str] = []

    @staticmethod
    def stock_config(role: str) -> dict[str, dict[str, Any]]:
        """Stock settings: some differ from the docs, some keys setup must not touch."""
        media = dict(ARR_MEDIA_MANAGEMENT.get(role, {}))
        media.update(importExtraFiles=False, extraFileExtensions="srt", enableMediaInfo=True)
        media.pop("recycleBinCleanupDays", None)  # a version without this setting
        media.update(id=1, chmodFolder="755")
        naming = {key: False for key in ARR_NAMING.get(role, {})}
        if "colonReplacementFormat" in naming:
            naming["colonReplacementFormat"] = "smart"
        naming.update(id=1, standardEpisodeFormat="{Series Title} - S{season:00}E{episode:00}")
        return {
            "mediamanagement": media,
            "naming": naming,
            "downloadclient": {
                "id": 1,
                "enableCompletedDownloadHandling": True,
                "autoRedownloadFailed": True,
            },
            "host": {
                "id": 1,
                "bindAddress": "*",
                "port": 8989,
                "urlBase": "",
                "enableSsl": False,
                "proxyEnabled": False,
                "logLevel": "info",
                "analyticsEnabled": True,
                "updateAutomatically": False,
                "authenticationMethod": "external",
            },
        }

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
        if resource.startswith("config/"):
            name, _, ident = resource.removeprefix("config/").partition("/")
            if name not in self.config:
                return _json(404, {"message": "Not Found"})
            if method == "GET":
                return _json(200, self.config[name])
            if method == "PUT" and ident == str(self.config[name]["id"]):
                body_data = json.loads(body or b"{}")
                if set(body_data) != set(self.config[name]):
                    return _json(400, [{"errorMessage": "settings object was not complete"}])
                self.config[name] = body_data
                self.puts.append(name)
                return _json(202, body_data)
            return _json(405, {"message": "Method not allowed"})
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
    """qBittorrent 5 style: a wrong password is a 401, the cookie name is configurable."""

    def __init__(
        self,
        user: str,
        password: str | None,
        *,
        cookie_name: str = "SID",
        status_on_fail=401,
        temporary: str = "",
    ):
        self.user = user
        self.password = password
        self.temporary = temporary  # qBittorrent >= 4.6.1 with no password set
        self.cookie_name = cookie_name
        self.status_on_fail = status_on_fail
        self.preferences: dict[str, Any] = {"save_path": "/downloads/", "temp_path_enabled": False}
        self.logins = 0

    def handle(self, method: str, path: str, headers: dict[str, str], body: bytes | None):
        if path == "/api/v2/auth/login" and method == "POST":
            form = dict(urllib.parse.parse_qsl((body or b"").decode()))
            expected = self.password if self.password is not None else self.temporary
            if form.get("username") == self.user and form.get("password") == expected:
                self.logins += 1
                cookies = f"theme=dark; path=/\n{self.cookie_name}=s3cr3t; HttpOnly; path=/"
                return Response(200, b"Ok.", {"set-cookie": cookies})
            if self.status_on_fail == 200:
                return Response(200, b"Fails.", {})
            return Response(self.status_on_fail, b"Unauthorized", {})
        if headers.get("Cookie") != f"{self.cookie_name}=s3cr3t":
            return Response(401, b"Unauthorized", {})
        if path == "/api/v2/app/preferences" and method == "GET":
            return _json(200, self.preferences)
        if path == "/api/v2/app/setPreferences" and method == "POST":
            form = dict(urllib.parse.parse_qsl((body or b"").decode()))
            changes = json.loads(form["json"])
            if "web_ui_password" in changes:
                self.user = changes.pop("web_ui_username", self.user)
                self.password = changes.pop("web_ui_password")
                self.temporary = ""
            self.preferences.update(changes)
            return Response(200, b"", {})
        return Response(404, b"Not Found", {})


def qbit_log(qbit: FakeQbit) -> str:
    """What ``docker logs qbittorrent`` prints for the fake's current state."""
    lines = [
        "WebUI will be started shortly after internal preparations. Please wait...",
        "To control qBittorrent, access the WebUI at: http://localhost:8080",
    ]
    if qbit.password is None:
        lines += [
            f"The WebUI administrator username is: {qbit.user}",
            "The WebUI administrator password was not set. A temporary password is provided "
            f"for this session: {qbit.temporary}",
            "You should set your own password in program preferences.",
        ]
    return "\n".join(lines)


class FakeSab:
    def __init__(self, api_key: str, *, servers: int = 1):
        self.api_key = api_key
        self.servers = [{"name": f"news{i}.example.com"} for i in range(servers)]
        self.categories = ["*", "movies", "tv", "audio", "software"]

    def handle(self, method: str, path: str, headers: dict[str, str], body: bytes | None):
        url = urllib.parse.urlsplit(path)
        query = dict(urllib.parse.parse_qsl(url.query))
        if url.path != "/api":
            return Response(404, b"Not Found", {})
        if query.get("apikey") != self.api_key:
            return _json(200, {"status": False, "error": "API Key Incorrect"})
        mode = query.get("mode")
        if mode == "get_config" and query.get("section") == "servers":
            return _json(200, {"config": {"servers": self.servers}})
        if mode == "get_cats":
            return _json(200, {"categories": self.categories})
        if mode == "set_config" and query.get("section") == "categories":
            if query["name"] not in self.categories:
                self.categories.append(query["name"])
            return _json(200, {"config": {"categories": [{"name": query["name"]}]}})
        return _json(200, {"status": False, "error": "not implemented"})


class FakePlex:
    def __init__(self, token: str):
        self.token = token
        self.sections: list[dict[str, Any]] = []
        self.refreshed: list[str] = []
        self.library_prefs: dict[str, dict[str, Any]] = {}
        # Plex defaults; one docs setting is missing, as in an older Plex
        self.prefs: dict[str, Any] = {
            key: (not value if isinstance(value, bool) else value)
            for key, value in PLEX_PREFERENCES.items()
            if key != "MusicAnalysisBehavior"
        }
        self.prefs.update(
            GenerateBIFBehavior="scheduled", TranscoderThrottleBuffer=60, secureConnections=1
        )
        self.prefs["FriendlyName"] = "saltbox"

    @staticmethod
    def _settings(values: dict[str, Any]) -> dict[str, Any]:
        def kind(value: Any) -> str:
            return (
                "bool" if isinstance(value, bool) else "int" if isinstance(value, int) else "text"
            )

        return {
            "MediaContainer": {
                "Setting": [{"id": k, "value": v, "type": kind(v)} for k, v in values.items()]
            }
        }

    @staticmethod
    def _apply(target: dict[str, Any], query: dict[str, str]) -> None:
        for key, raw in query.items():
            if key not in target:
                continue
            old = target[key]
            if isinstance(old, bool):
                target[key] = raw in ("1", "true")
            elif isinstance(old, int):
                target[key] = int(raw)
            else:
                target[key] = raw

    def handle(self, method: str, path: str, headers: dict[str, str], body: bytes | None):
        if headers.get("X-Plex-Token") != self.token:
            return Response(401, b"Unauthorized", {})
        url = urllib.parse.urlsplit(path)
        if url.path == "/library/sections" and method == "GET":
            return _json(200, {"MediaContainer": {"Directory": copy.deepcopy(self.sections)}})
        query = dict(urllib.parse.parse_qsl(url.query))
        if url.path == "/:/prefs" and method == "GET":
            return _json(200, self._settings(self.prefs))
        if url.path == "/:/prefs" and method == "PUT":
            self._apply(self.prefs, query)
            return Response(200, b"", {})
        if url.path.endswith("/prefs") and url.path.startswith("/library/sections/"):
            key = url.path.split("/")[3]
            if key not in self.library_prefs:
                return Response(404, b"Not Found", {})
            if method == "GET":
                return _json(200, self._settings(self.library_prefs[key]))
            self._apply(self.library_prefs[key], query)
            return Response(200, b"", {})
        if url.path == "/library/sections" and method == "POST":
            key = str(len(self.sections) + 1)
            prefs = {"enableBIFGeneration": True} if query["type"] in ("movie", "show") else {}
            self._apply(
                prefs,
                {
                    k[6:-1]: v
                    for k, v in query.items()
                    if k.startswith("prefs[") and k.endswith("]")
                },
            )
            self.library_prefs[key] = prefs
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
