"""Link a Plex account before the install, so the Plex role never has to stop.

Saltbox's ``plex_auth_token`` role creates a PIN on plex.tv, then pauses and
asks the person to log in and press Enter. Run without a terminal, as the
installer runs ``sb``, Ansible skips that pause, no token is created and the
Plex step fails. The role skips the whole prompt when ``/opt/saltbox/plex.ini``
already holds a valid token, so the installer does the same PIN login itself
and saves the result where the role looks.

The PIN is created without ``strong``, which gives a four-character code the
person can type at https://plex.tv/link from any device, a phone included.
"""

from __future__ import annotations

import configparser
import json
import os
import pwd
import secrets
import string
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from .layout import Layout

API = "https://plex.tv/api/v2"
LINK_PAGE = "https://plex.tv/link"
PRODUCT = "Saltbox"  # what the role sends, so the device shows up the same in Plex
TIMEOUT = 15

Opener = Callable[[urllib.request.Request], tuple[int, bytes]]


class PlexError(RuntimeError):
    pass


@dataclass
class Pin:
    id: int
    code: str
    client_id: str

    @property
    def link_url(self) -> str:
        return LINK_PAGE

    @property
    def auth_url(self) -> str:
        """The long form, for people who prefer to open a link directly."""
        params = urllib.parse.urlencode(
            {"clientID": self.client_id, "code": self.code, "context[device][product]": PRODUCT}
        )
        return f"https://app.plex.tv/auth#?{params}"


def new_client_id() -> str:
    """A client identifier in the role's own format: ``Saltbox`` plus 8 characters."""
    alphabet = string.ascii_lowercase + string.digits
    return PRODUCT + "".join(secrets.choice(alphabet) for _ in range(8))


def _urlopen(request: urllib.request.Request) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise PlexError(f"cannot reach plex.tv: {error}") from error


class PlexClient:
    def __init__(self, client_id: str | None = None, *, opener: Opener | None = None):
        self.client_id = client_id or new_client_id()
        self._open = opener or _urlopen

    def _headers(self, token: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "X-Plex-Product": PRODUCT,
            "X-Plex-Version": "1.0.0",
            "X-Plex-Client-Identifier": self.client_id,
            "X-Plex-Platform": "Linux",
            "X-Plex-Device-Name": PRODUCT,
        }
        if token:
            headers["X-Plex-Token"] = token
        return headers

    def _request(
        self, method: str, path: str, *, token: str | None = None, form: dict | None = None
    ) -> tuple[int, Any]:
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        headers = self._headers(token)
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(f"{API}{path}", data=data, headers=headers, method=method)
        status, body = self._open(request)
        try:
            payload = json.loads(body.decode("utf-8") or "null")
        except ValueError:
            payload = None
        return status, payload

    def create_pin(self) -> Pin:
        status, payload = self._request("POST", "/pins", form={"strong": "false"})
        if status not in (200, 201) or not isinstance(payload, dict):
            raise PlexError(f"plex.tv refused to create a PIN (HTTP {status})")
        return Pin(id=int(payload["id"]), code=str(payload["code"]), client_id=self.client_id)

    def check_pin(self, pin: Pin) -> str | None:
        """The auth token once the person has linked the code, else ``None``."""
        status, payload = self._request("GET", f"/pins/{pin.id}")
        if status == 404:
            raise PlexError("the code expired; ask for a new one")
        if status != 200 or not isinstance(payload, dict):
            raise PlexError(f"plex.tv answered HTTP {status} while checking the code")
        token = payload.get("authToken")
        return str(token).strip() if token else None

    def username(self, token: str) -> str:
        """Validate ``token`` the way the role does and return the account name."""
        status, payload = self._request("GET", "/user", token=token)
        if status == 401:
            raise PlexError("plex.tv rejected the token")
        if status != 200 or not isinstance(payload, dict):
            raise PlexError(f"plex.tv answered HTTP {status} while checking the token")
        return str(payload.get("username") or payload.get("title") or payload.get("email") or "")


# -- the facts file the plex_auth_token role reads ------------------------------
def facts_path(layout: Layout) -> Path:
    return layout.facts_dir / "plex.ini"


def write_plex_facts(
    layout: Layout, *, instance: str, client_id: str, token: str, owner: str | None = None
) -> Path:
    """Save the token where ``saltbox_facts`` keeps it, in the same INI format.

    Other keys in the file are kept. The file ends up 0640 and owned by the
    Saltbox user, as the role leaves it.
    """
    path = facts_path(layout)
    path.parent.mkdir(parents=True, exist_ok=True)
    config = _parser()
    if path.exists():
        config.read(path, encoding="utf-8")
    if not config.has_section(instance):
        config.add_section(instance)
    config.set(instance, "client_identifier", client_id)
    config.set(instance, "token", token)
    buffer = StringIO()
    config.write(buffer)
    tmp = path.with_suffix(".ini.tmp")
    tmp.write_text(buffer.getvalue(), encoding="utf-8")
    tmp.chmod(0o640)
    if owner:
        try:
            entry = pwd.getpwnam(owner)
        except KeyError:
            entry = None
        if entry is not None and os.geteuid() == 0:
            os.chown(tmp, entry.pw_uid, entry.pw_gid)
    tmp.replace(path)
    return path


def read_plex_facts(layout: Layout, instance: str) -> dict[str, str]:
    path = facts_path(layout)
    if not path.exists():
        return {}
    config = _parser()
    config.read(path, encoding="utf-8")
    return dict(config.items(instance)) if config.has_section(instance) else {}


class _CaseSensitive(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return str(optionstr)


def _parser() -> configparser.ConfigParser:
    return _CaseSensitive(
        interpolation=None,
        comment_prefixes=("#",),
        inline_comment_prefixes=None,
        delimiters=("=",),
        empty_lines_in_values=False,
    )
