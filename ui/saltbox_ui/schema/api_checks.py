"""Live credential checks, the async part of ``sb validate-config``.

Kept apart from the pure validators so unit tests never touch the network.
Only the standard library is used; the Cloudflare client sb uses is not
needed for three GET requests.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from tld import get_fld
from tld.exceptions import TldBadUrl, TldDomainNotFound

from . import validators as v

CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"
DOCKERHUB_LOGIN = "https://hub.docker.com/v2/users/login/"
TIMEOUT = 10


def root_domain(fqdn: str) -> str:
    if not fqdn:
        raise ValueError("empty domain name")
    try:
        return get_fld(fqdn, fix_protocol=True)
    except (TldBadUrl, TldDomainNotFound) as error:
        raise ValueError(f"invalid domain format: {fqdn}") from error


def _request(url: str, headers: dict[str, str], data: bytes | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers, data=data)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _cloudflare_headers(credentials: dict[str, str]) -> dict[str, str]:
    if "scoped_token" in credentials:
        return {"Authorization": f"Bearer {credentials['scoped_token']}"}
    return {"X-Auth-Key": credentials["api"], "X-Auth-Email": credentials["email"]}


def check_cloudflare(value: Any, config: dict[str, Any]) -> None:
    """Verify Cloudflare credentials, zone access and SSL mode like sb does."""
    credentials = v.parse_cloudflare_credentials(value)
    if credentials is None:
        return
    user = config.get("user")
    domain = user.get("domain") if isinstance(user, dict) else None
    if not isinstance(domain, str):
        raise ValueError("user domain is required for Cloudflare validation")
    headers = _cloudflare_headers(credentials)
    if "scoped_token" not in credentials:
        try:
            _request(f"{CLOUDFLARE_API}/user", headers)
        except (urllib.error.URLError, ValueError) as error:
            raise ValueError(f"cloudflare Global API key verification failed: {error}") from error
    zone_name = root_domain(domain)
    try:
        zones = _request(
            f"{CLOUDFLARE_API}/zones?{urllib.parse.urlencode({'name': zone_name})}", headers
        )
    except (urllib.error.URLError, ValueError) as error:
        raise ValueError(f"Cloudflare zone lookup failed for {zone_name}: {error}") from error
    results = zones.get("result") or []
    if not results:
        raise ValueError(
            f"Cloudflare zone lookup failed: zone {zone_name} was not returned for these "
            "credentials (check DNS and Zones -> Zone -> Read and the zone scope)"
        )
    zone_id = results[0]["id"]
    try:
        ssl = _request(f"{CLOUDFLARE_API}/zones/{zone_id}/settings/ssl", headers)
    except (urllib.error.URLError, ValueError) as error:
        raise ValueError(
            f"Cloudflare SSL/TLS mode lookup failed for {zone_name}: {error} "
            "(check DNS and Zones -> Zone Settings -> Read)"
        ) from error
    mode = (ssl.get("result") or {}).get("value")
    if mode in {"flexible", "off"}:
        raise ValueError(
            f"incompatible SSL/TLS mode detected: '{mode}'. Change the encryption mode for "
            f"{zone_name} to 'Full' or 'Full (strict)' in the Cloudflare dashboard"
        )


def check_dockerhub(value: Any, _config: dict[str, Any]) -> None:
    credentials = v.parse_dockerhub_credentials(value)
    if credentials is None:
        return
    username, token = credentials
    payload = json.dumps({"username": username, "password": token}).encode("utf-8")
    try:
        _request(DOCKERHUB_LOGIN, {"Content-Type": "application/json"}, payload)
    except urllib.error.HTTPError as error:
        message = ""
        try:
            body = json.loads(error.read().decode("utf-8"))
            message = body.get("message") or body.get("details") or ""
        except (ValueError, OSError):
            pass
        suffix = f": {message}" if message else ""
        raise ValueError(f"docker hub authentication failed (HTTP {error.code}){suffix}") from error
    except urllib.error.URLError as error:
        raise ValueError(f"docker hub authentication failed: {error}") from error


def default_api_checks() -> dict[str, Any]:
    return {
        "validate_cloudflare_config": check_cloudflare,
        "validate_dockerhub_config": check_dockerhub,
    }
