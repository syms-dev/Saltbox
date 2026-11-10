"""Containers Saltbox manages.

The Docker SDK is an optional extra, and a plain ``pipx install`` of the UI
leaves it out, so the ``docker`` command line is used whenever the SDK is
missing or fails. Both return the same records.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

MANAGED_LABEL = "com.github.saltbox.saltbox_managed"
HOST_RE = re.compile(r"Host\(`([^`]+)`\)")

Runner = Callable[[list[str]], tuple[int, str]]


def _run(args: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return result.returncode, result.stdout if result.returncode == 0 else result.stderr


def web_urls(name: str, labels: dict[str, str]) -> list[str]:
    """The addresses Traefik serves a container on, from its router labels.

    Saltbox names the HTTPS router after the container, with ``-http`` and
    ``-api`` variants beside it; the main router comes first, and rules that
    only match a path prefix (the API routes) are skipped.
    """
    rules: list[tuple[int, str]] = []
    for key, value in labels.items():
        if not (key.startswith("traefik.http.routers.") and key.endswith(".rule")):
            continue
        router = key[len("traefik.http.routers.") : -len(".rule")]
        if "PathPrefix" in str(value) or router.endswith("-api"):
            continue
        rank = 0 if router == name else (1 if router == f"{name}-http" else 2)
        rules.append((rank, str(value)))
    urls: list[str] = []
    for _, rule in sorted(rules):
        for host in HOST_RE.findall(rule):
            url = f"https://{host}"
            if url not in urls:
                urls.append(url)
    return urls


def _record(attrs: dict[str, Any], image: str = "") -> dict[str, Any]:
    config = attrs.get("Config") or {}
    labels = config.get("Labels") or {}
    state = attrs.get("State") or {}
    name = str(attrs.get("Name", "")).lstrip("/")
    return {
        "name": name,
        "id": str(attrs.get("Id", ""))[:12],
        "image": image or str(config.get("Image", "")),
        "image_ref": str(config.get("Image", "")),
        "image_id": str(attrs.get("Image", "")),
        "network_mode": str((attrs.get("HostConfig") or {}).get("NetworkMode", "")),
        "urls": web_urls(name, labels),
        "status": str(state.get("Status", "")),
        "health": (state.get("Health") or {}).get("Status"),
        "started_at": state.get("StartedAt"),
        "managed": str(labels.get(MANAGED_LABEL, "false")).lower() == "true",
        "traefik": str(labels.get("traefik.enable", "false")).lower() == "true",
        "labels": labels,
    }


def list_containers_cli(runner: Runner | None = None) -> list[dict[str, Any]]:
    """``docker ps -aq`` then ``docker inspect``: full labels and health, no SDK needed."""
    run = runner or _run
    if runner is None and shutil.which("docker") is None:
        raise RuntimeError("the docker command is not installed")
    code, output = run(["docker", "ps", "-aq", "--no-trunc"])
    if code != 0:
        raise RuntimeError(output.strip() or "docker ps failed")
    ids = output.split()
    if not ids:
        return []
    code, output = run(["docker", "inspect", *ids])
    if code != 0:
        raise RuntimeError(output.strip() or "docker inspect failed")
    return sorted((_record(item) for item in json.loads(output or "[]")), key=lambda c: c["name"])


def list_containers(*, all_containers: bool = True) -> list[dict[str, Any]]:
    try:
        import docker  # type: ignore[import-not-found]
    except ImportError:
        return list_containers_cli()
    try:
        client = docker.from_env()
        containers = client.containers.list(all=all_containers)
    except Exception:  # SDK present but unusable (socket, API version): use the CLI
        return list_containers_cli()
    result = []
    for container in containers:
        image = ", ".join(container.image.tags) if container.image else ""
        result.append(_record(container.attrs or {}, image))
    return sorted(result, key=lambda c: c["name"])


# -- actions -------------------------------------------------------------------
CONTAINER_ACTIONS = ("start", "stop", "restart")
MAX_LOG_LINES = 2000


def container_action(name: str, action: str, runner: Runner | None = None) -> None:
    """Start, stop or restart a container through the docker CLI."""
    if action not in CONTAINER_ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    code, output = (runner or _run_long)(["docker", action, "--", name])
    if code != 0:
        raise RuntimeError(output.strip() or f"docker {action} {name} failed")


def container_logs(name: str, tail: int = 300, runner: Runner | None = None) -> list[str]:
    """The last ``tail`` log lines of a container, stdout and stderr merged, oldest first."""
    tail = max(1, min(int(tail), MAX_LOG_LINES))
    code, output = (runner or _run_merged)(
        ["docker", "logs", "--tail", str(tail), "--timestamps", "--", name]
    )
    if code != 0:
        raise RuntimeError(output.strip() or f"docker logs {name} failed")
    return output.splitlines()[-tail:]


def _run_long(args: list[str]) -> tuple[int, str]:
    """Like ``_run`` with the time a container needs to stop (docker's 10 s plus slack)."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return result.returncode, result.stdout if result.returncode == 0 else result.stderr


def _run_merged(args: list[str]) -> tuple[int, str]:
    """Run with stderr folded into stdout: containers log to both."""
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return result.returncode, result.stdout
