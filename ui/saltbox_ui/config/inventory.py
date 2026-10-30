"""The inventory file, ``inventories/host_vars/localhost.yml``.

Saltbox customisation is a flat mapping of variable overrides. Two scopes
exist for roles that support instances: ``<role>_role<suffix>`` applies to
every instance, ``<instance><suffix>`` applies to one. Instance-scoped wins.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap

from ..yamlio import coerce_scalar, load_yaml, save_yaml, to_plain

INVENTORY_HEADER = (
    "---\n"
    "# Saltbox inventory. Variables here override role defaults.\n"
    "# https://docs.saltbox.dev/saltbox/inventory/\n"
)


def role_key(role: str, suffix: str) -> str:
    """Role-scoped variable name, e.g. ``sonarr_role_docker_image_tag``."""
    return f"{role}_role{suffix}"


def instance_key(instance: str, suffix: str) -> str:
    """Instance-scoped variable name, e.g. ``sonarr4k_docker_image_tag``."""
    return f"{instance}{suffix}"


class Inventory:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> CommentedMap:
        if not self.path.exists():
            return CommentedMap()
        data = load_yaml(self.path)
        return data if isinstance(data, CommentedMap) else CommentedMap()

    def as_dict(self) -> dict[str, Any]:
        return to_plain(self.load())

    def get(self, key: str, default: Any = None) -> Any:
        data = self.load()
        return to_plain(data[key]) if key in data else default

    def set(self, key: str, value: Any) -> None:
        if isinstance(value, str):
            value = coerce_scalar(value)
        data = self.load()
        data[key] = value
        save_yaml(self.path, data, header=INVENTORY_HEADER)

    def update(self, values: dict[str, Any]) -> None:
        data = self.load()
        for key, value in values.items():
            data[key] = value
        save_yaml(self.path, data, header=INVENTORY_HEADER)

    def unset(self, key: str) -> bool:
        data = self.load()
        if key not in data:
            return False
        del data[key]
        save_yaml(self.path, data, header=INVENTORY_HEADER)
        return True

    # -- instances and scopes --------------------------------------------
    def instances(self, role: str, default: list[str] | None = None) -> list[str]:
        """Instance names for ``role``: the ``<role>_instances`` override or the default."""
        value = self.get(f"{role}_instances")
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return list(value)
        return list(default) if default is not None else [role]

    def overrides_for(self, role: str, instances: list[str]) -> dict[str, dict[str, Any]]:
        """Overrides touching ``role`` grouped by scope.

        Returns ``{"role": {...}, "<instance>": {...}, "other": {...}}`` where
        ``other`` holds ``<role>_*`` keys that are neither role nor instance scoped.
        """
        data = self.as_dict()
        role_prefix = f"{role}_role_"
        grouped: dict[str, dict[str, Any]] = {"role": {}, "other": {}}
        for instance in instances:
            grouped[instance] = {}
        # Longest instance names first so ``sonarr4k_x`` is not claimed by ``sonarr``.
        ordered = sorted(instances, key=len, reverse=True)
        for key, value in data.items():
            if key.startswith(role_prefix):
                grouped["role"][key] = value
                continue
            owner = next((i for i in ordered if key.startswith(f"{i}_")), None)
            if owner is not None:
                grouped[owner][key] = value
            elif key.startswith(f"{role}_"):
                grouped["other"][key] = value
        return grouped

    def effective(self, role: str, suffix: str, instance: str, default: Any = None) -> Any:
        """Resolve a value the way role_var does: instance, then role, then default."""
        data = self.as_dict()
        for key in (instance_key(instance, suffix), role_key(role, suffix)):
            if key in data:
                return data[key]
        return default
