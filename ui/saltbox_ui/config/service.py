"""The six Saltbox configuration files.

Loading follows the playbook's ``vars_files`` rule: when a file is missing
the matching ``defaults/*.default`` is used. Saving is comment preserving and
atomic. Validation uses the schemas in ``schema/`` with the same rules as
``sb validate-config``.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap

from ..layout import Layout
from ..schema import Issue, Schema, ValidationContext, load_schema
from ..schema import validators as v
from ..yamlio import (
    coerce_scalar,
    find_duplicate_keys,
    get_path,
    load_yaml,
    save_yaml,
    set_path,
    to_plain,
)


@dataclass(frozen=True)
class ConfigFile:
    name: str
    filename: str
    schema: str | None
    optional: bool = False
    has_default: bool = True


CONFIG_FILES: dict[str, ConfigFile] = {
    "accounts": ConfigFile("accounts", "accounts.yml", "accounts.schema.yml"),
    "settings": ConfigFile("settings", "settings.yml", "settings.schema.yml"),
    "adv_settings": ConfigFile("adv_settings", "adv_settings.yml", "adv_settings.schema.yml"),
    "backup_config": ConfigFile("backup_config", "backup_config.yml", "backup_config.schema.yml"),
    "providers": ConfigFile("providers", "providers.yml", None),
    "hetzner_vlan": ConfigFile("hetzner_vlan", "hetzner_vlan.yml", "hetzner_vlan.schema.yml"),
    "motd": ConfigFile("motd", "motd.yml", "motd.schema.yml", optional=True, has_default=False),
}


def rclone_remote_lister(layout: Layout, user: str | None) -> Callable[[], list[str] | None]:
    """Build a lister that runs ``rclone listremotes`` as the Saltbox user."""

    def list_remotes() -> list[str] | None:
        if shutil.which(str(layout.rclone_binary)) is None and not layout.rclone_binary.exists():
            return None
        if not user:
            return None
        config = Path(f"/home/{user}/.config/rclone/rclone.conf")
        if not config.exists():
            return None
        command = ["sudo", "-u", user, str(layout.rclone_binary), "listremotes"]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env={"RCLONE_CONFIG": str(config), "PATH": "/usr/bin:/bin:/usr/local/bin"},
        )
        if result.returncode != 0:
            raise OSError(result.stderr.strip() or "rclone listremotes failed")
        return [line.strip().rstrip(":") for line in result.stdout.splitlines() if line.strip()]

    return list_remotes


class ConfigService:
    def __init__(
        self,
        layout: Layout,
        *,
        list_remotes: Callable[[], list[str] | None] | None = None,
        api_checks: dict[str, Any] | None = None,
    ):
        self.layout = layout
        self._list_remotes = list_remotes
        self._api_checks = api_checks

    # -- paths -------------------------------------------------------------
    def spec(self, name: str) -> ConfigFile:
        try:
            return CONFIG_FILES[name]
        except KeyError as error:
            raise KeyError(f"unknown config file '{name}'") from error

    def path(self, name: str) -> Path:
        return self.layout.repo / self.spec(name).filename

    def default_path(self, name: str) -> Path | None:
        spec = self.spec(name)
        if not spec.has_default:
            return None
        return self.layout.defaults_dir / f"{spec.filename}.default"

    def exists(self, name: str) -> bool:
        return self.path(name).exists()

    def source(self, name: str) -> str:
        """``file``, ``default`` or ``missing`` for where a load would read from."""
        if self.exists(name):
            return "file"
        default = self.default_path(name)
        if default is not None and default.exists():
            return "default"
        return "missing"

    # -- load and save -------------------------------------------------------
    def load(self, name: str) -> CommentedMap:
        """Round-trip mapping from the file, else the default. Never ``None``."""
        path = self.path(name)
        if not path.exists():
            default = self.default_path(name)
            if default is None or not default.exists():
                return CommentedMap()
            path = default
        data = load_yaml(path)
        return data if isinstance(data, CommentedMap) else CommentedMap()

    def load_plain(self, name: str) -> dict[str, Any]:
        return to_plain(self.load(name))

    def ensure_exists(self, name: str) -> bool:
        """Copy the default into place when the file is missing. Returns True if copied."""
        path = self.path(name)
        if path.exists():
            return False
        default = self.default_path(name)
        if default is None or not default.exists():
            return False
        shutil.copyfile(default, path)
        path.chmod(0o640)
        return True

    def save(self, name: str, data: CommentedMap) -> None:
        save_yaml(self.path(name), data)

    def get(self, name: str, dotted: str) -> Any:
        return to_plain(get_path(self.load(name), dotted))

    def set(self, name: str, dotted: str, value: Any) -> None:
        if isinstance(value, str):
            value = coerce_scalar(value)
        data = self.load(name)
        set_path(data, dotted, value)
        self.save(name, data)

    # -- validation ------------------------------------------------------------
    def schema(self, name: str) -> Schema | None:
        spec = self.spec(name)
        if spec.schema is None:
            return None
        return load_schema(self.layout.schema_dir / spec.schema)

    def context(self, *, api_checks: bool = False) -> ValidationContext:
        lister = self._list_remotes
        if lister is None:
            user = self._saltbox_user()
            lister = rclone_remote_lister(self.layout, user)
        checks = self._api_checks
        if checks is None and api_checks:
            from ..schema.api_checks import default_api_checks

            checks = default_api_checks()
        return ValidationContext(
            validators=v.default_validators(lister),
            api_checks=checks or {},
            run_api_checks=api_checks,
        )

    def _saltbox_user(self) -> str | None:
        try:
            accounts = self.load_plain("accounts")
        except (OSError, ValueError):
            return None
        user = accounts.get("user")
        if isinstance(user, dict) and isinstance(user.get("name"), str):
            return user["name"]
        return None

    def validate(self, name: str, *, api_checks: bool = False) -> list[Issue]:
        spec = self.spec(name)
        path = self.path(name)
        if not path.exists():
            if spec.optional:
                return []
            return [Issue("", f"required config file not found: {path}")]
        text = path.read_text(encoding="utf-8")
        duplicates = find_duplicate_keys(text)
        if duplicates:
            return [Issue(dup.split(" ")[0], f"duplicate key: {dup}") for dup in duplicates]
        schema = self.schema(name)
        if schema is None:
            return []
        try:
            data = to_plain(load_yaml(path))
        except Exception as error:
            return [Issue("", f"invalid YAML in {path}: {error}")]
        return schema.validate(
            data if data is not None else {}, self.context(api_checks=api_checks)
        )

    def validate_inventory(self) -> list[Issue]:
        path = self.layout.inventory
        if not path.exists():
            return []
        duplicates = find_duplicate_keys(path.read_text(encoding="utf-8"))
        return [Issue(dup.split(" ")[0], f"duplicate key: {dup}") for dup in duplicates]

    def validate_all(self, *, api_checks: bool = False) -> dict[str, list[Issue]]:
        results = {name: self.validate(name, api_checks=api_checks) for name in CONFIG_FILES}
        results["inventory"] = self.validate_inventory()
        return results
