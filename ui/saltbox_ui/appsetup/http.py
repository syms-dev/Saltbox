"""A small JSON-over-HTTP client for talking to the apps' own APIs.

Requests go straight to the containers (``http://sonarr:8989``), never
through a proxy: Saltbox's sdhm service puts every container name on the
saltbox network into ``/etc/hosts``. The transport is a plain function so
tests can replace the network with in-memory fakes.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

TIMEOUT = 20


class SetupError(RuntimeError):
    """An app could not be reached or refused a request."""


@dataclass
class Response:
    status: int
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        text = self.body.decode("utf-8", errors="replace").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError:
            return None

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


Transport = Callable[[str, str, dict[str, str], bytes | None], Response]

_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> Response:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with _NO_PROXY.open(request, timeout=TIMEOUT) as response:
            return Response(
                response.status,
                response.read(),
                {k.lower(): v for k, v in response.headers.items()},
            )
    except urllib.error.HTTPError as error:
        return Response(
            error.code, error.read(), {k.lower(): v for k, v in (error.headers or {}).items()}
        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        host = urllib.parse.urlsplit(url).netloc
        raise SetupError(f"cannot reach {host}: {reason}") from error


def describe_error(response: Response) -> str:
    """Turn an app's error body into one readable line."""
    data = response.json()
    messages: list[str] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                message = item.get("errorMessage") or item.get("message")
                if message:
                    messages.append(str(message))
    elif isinstance(data, dict):
        for key in ("message", "error", "errorMessage", "description"):
            if data.get(key):
                messages.append(str(data[key]))
                break
    if not messages and response.text.strip():
        messages.append(response.text.strip()[:200])
    return "; ".join(messages) or f"HTTP {response.status}"


class Client:
    """JSON client for one app, with fixed headers such as an API key."""

    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        transport: Transport | None = None,
        name: str = "",
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Accept": "application/json", **(headers or {})}
        self.transport = transport or urllib_transport
        self.name = name or urllib.parse.urlsplit(self.base_url).hostname or self.base_url

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        form: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        ok: tuple[int, ...] = (200, 201, 202, 204),
    ) -> Response:
        url = self.base_url + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        all_headers = {**self.headers, **(headers or {})}
        body: bytes | None = None
        if json_body is not None:
            body = json.dumps(json_body).encode()
            all_headers["Content-Type"] = "application/json"
        elif form is not None:
            body = urllib.parse.urlencode(form).encode()
            all_headers["Content-Type"] = "application/x-www-form-urlencoded"
        response = self.transport(method, url, all_headers, body)
        if response.status not in ok:
            raise SetupError(f"{self.name}: {describe_error(response)}")
        return response

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs).json()

    def post(self, path: str, body: Any = None, **kwargs: Any) -> Any:
        return self.request("POST", path, json_body=body, **kwargs).json()

    def put(self, path: str, body: Any = None, **kwargs: Any) -> Any:
        return self.request("PUT", path, json_body=body, **kwargs).json()
