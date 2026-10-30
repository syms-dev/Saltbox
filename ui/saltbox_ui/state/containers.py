"""Containers Saltbox manages, through the Docker SDK when it is installed."""

from __future__ import annotations

from typing import Any

MANAGED_LABEL = "com.github.saltbox.saltbox_managed"


def list_containers(*, all_containers: bool = True) -> list[dict[str, Any]]:
    try:
        import docker  # type: ignore[import-not-found]
    except ImportError as error:
        raise RuntimeError("the docker package is not installed") from error
    client = docker.from_env()
    result = []
    for container in client.containers.list(all=all_containers):
        attrs = container.attrs or {}
        labels = attrs.get("Config", {}).get("Labels") or {}
        state = attrs.get("State", {})
        result.append(
            {
                "name": container.name,
                "id": container.short_id,
                "image": ", ".join(container.image.tags) if container.image else "",
                "status": container.status,
                "health": (state.get("Health") or {}).get("Status"),
                "started_at": state.get("StartedAt"),
                "managed": labels.get(MANAGED_LABEL, "false").lower() == "true",
                "traefik": labels.get("traefik.enable", "false").lower() == "true",
                "labels": labels,
            }
        )
    return sorted(result, key=lambda c: c["name"])
