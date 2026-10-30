"""Parse a role's ``defaults/main.yml`` into typed, documented fields.

Follows the conventions the Saltbox docs generator documents for role
authors: hash-banner sections, ``Sub-section Start/End`` markers, comment
blocks attached to the next variable, ``[GLOBAL]`` and ``[NOGLOBAL]`` shared
text, ``Skip docs`` and the inventory prohibition, ``_instances`` detection,
``_default``/``_custom`` pairs, and type inference from the value with the
same suffix rules the docs use for Jinja expressions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..yamlio import load_text, to_plain

BANNER_RE = re.compile(r"^#{10,}\s*$")
SECTION_NAME_RE = re.compile(r"^#\s*(.+?)\s*#*\s*$")
SUBSECTION_START_RE = re.compile(r"^(.+?)\s+-\s+Sub-section Start$")
SUBSECTION_END_RE = re.compile(r"^(.+?)\s+-\s+Sub-section End$")
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:")
JINJA_RE = re.compile(r"\{\{|\{%")

SKIP_DOCS = "Skip docs"
DO_NOT_EDIT = "Do not edit or override using the inventory"
DOCS_ONLY_SECTIONS = {"Paths"}

# Type inference for Jinja-valued variables, from the docs generator's config.
EXACT_TYPES = {
    "_depends_on_healthchecks": "string (true/false)",
    "_depends_on_delay": "string (number)",
    "_depends_on": "string",
}
SUFFIX_PATTERNS: list[tuple[str, str]] = [
    ("_scheme", "string (http/https)"),
    ("_enabled", "bool"),
    ("_proxy", "bool"),
    ("_domain", "string"),
    ("_subdomain", "string"),
    ("_url", "string"),
    ("_port", "string (number)"),
    ("_timeout", "string (number)"),
]
OVERRIDE_TYPES = {
    "_dns_proxy": "bool",
    "_dns_record": "string",
    "_dns_zone": "string",
}
FILTER_TYPES = {
    "saltbox_argv": "list",
    "traefik_certificate_domains": "list",
    "traefik_certificate_labels": "dict",
    "traefik_certificate_plan": "dict",
}
DOCKER_LIST_SUFFIXES = {
    "capabilities",
    "cap_drop",
    "commands",
    "device_cgroup_rules",
    "device_read_bps",
    "device_read_iops",
    "device_requests",
    "device_write_bps",
    "device_write_iops",
    "devices",
    "dns_opts",
    "dns_search_domains",
    "dns_servers",
    "entrypoint",
    "exposed_ports",
    "groups",
    "links",
    "mounts",
    "networks",
    "ports",
    "security_opts",
    "tmpfs",
    "ulimits",
    "volumes",
    "volumes_from",
}
DOCKER_DICT_SUFFIXES = {
    "envs",
    "healthcheck",
    "hosts",
    "labels",
    "log_options",
    "storage_opts",
    "sysctls",
}
DOCKER_BOOL_SUFFIXES = {
    "auto_remove",
    "cleanup",
    "detach",
    "force_kill",
    "hosts_use_common",
    "image_pull",
    "init",
    "keep_volumes",
    "labels_use_common",
    "oom_killer",
    "output_logs",
    "paused",
    "privileged",
    "read_only",
    "recreate",
    "volumes_global",
}
DOCKER_INT_SUFFIXES = {
    "blkio_weight",
    "cpu_period",
    "cpu_quota",
    "cpu_shares",
    "create_timeout",
    "healthy_wait_timeout",
    "memory_swappiness",
    "oom_score_adj",
    "restart_retries",
    "stop_timeout",
}


@dataclass
class Field:
    name: str
    section: str
    subsection: str | None
    value: Any
    raw: str
    type: str
    help: list[str] = field(default_factory=list)
    scope: str = "global"  # "role", "instance-default", "instances", "global"
    suffix: str | None = None  # for role-scoped fields: part after ``<role>_role``
    hidden: bool = False
    hidden_reason: str | None = None  # "skip-docs", "do-not-edit", "aggregate", "lookup"
    jinja: bool = False
    line: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "section": self.section,
            "subsection": self.subsection,
            "value": self.value,
            "raw": self.raw,
            "type": self.type,
            "help": self.help,
            "scope": self.scope,
            "suffix": self.suffix,
            "hidden": self.hidden,
            "hidden_reason": self.hidden_reason,
            "jinja": self.jinja,
            "line": self.line,
        }


@dataclass
class RoleDefaults:
    role: str
    path: Path
    fields: list[Field]
    sections: list[str]
    instances_var: str | None = None
    default_instances: list[str] = field(default_factory=list)

    @property
    def supports_instances(self) -> bool:
        return self.instances_var is not None

    def visible(self) -> list[Field]:
        return [f for f in self.fields if not f.hidden]

    def by_name(self) -> dict[str, Field]:
        return {f.name: f for f in self.fields}

    def instance_key(self, fld: Field, instance: str) -> str | None:
        """Instance-scoped override name for a role-scoped field."""
        if fld.scope != "role" or fld.suffix is None:
            return None
        return f"{instance}{fld.suffix}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "path": str(self.path),
            "sections": self.sections,
            "instances_var": self.instances_var,
            "default_instances": self.default_instances,
            "fields": [f.as_dict() for f in self.fields],
        }


def parse_role_defaults(role: str, path: Path) -> RoleDefaults:
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    data = load_text(text)
    if data is None:
        return RoleDefaults(role, Path(path), [], [])
    if not hasattr(data, "lc"):
        raise ValueError(f"{path} is not a mapping")

    key_lines: dict[int, str] = {}
    for key in data:
        key_lines[data.lc.key(key)[0]] = str(key)
    starts = sorted(key_lines)

    start_index = next((i for i, line in enumerate(lines) if line.strip() == "---"), -1) + 1

    section = "General"
    subsection: str | None = None
    global_help: list[str] = []
    pending: list[str] = []
    noglobal = False
    skip_docs = False
    do_not_edit = False
    sections: list[str] = []
    fields: list[Field] = []

    i = start_index
    while i < len(lines):
        line = lines[i]
        if i in key_lines:
            name = key_lines[i]
            next_start = next((s for s in starts if s > i), len(lines))
            raw = _raw_value(lines, i, next_start)
            value = to_plain(data[name])
            help_lines = ([] if noglobal else list(global_help)) + pending
            fld = Field(
                name=name,
                section=section,
                subsection=subsection,
                value=value,
                raw=raw,
                type=infer_type(name, value, raw),
                help=help_lines,
                jinja=bool(JINJA_RE.search(raw)),
                line=i + 1,
            )
            if do_not_edit:
                fld.hidden, fld.hidden_reason = True, "do-not-edit"
            elif skip_docs:
                fld.hidden, fld.hidden_reason = True, "skip-docs"
            fields.append(fld)
            if section not in sections:
                sections.append(section)
            pending, noglobal, skip_docs, do_not_edit = [], False, False, False
            i += 1
            continue
        if BANNER_RE.match(line):
            if (
                i + 2 < len(lines)
                and BANNER_RE.match(lines[i + 2])
                and lines[i + 1].startswith("#")
                and not BANNER_RE.match(lines[i + 1])
            ):
                match = SECTION_NAME_RE.match(lines[i + 1])
                section = match.group(1) if match else "General"
                subsection = None
                global_help, pending = [], []
                noglobal = skip_docs = do_not_edit = False
                i += 3
                continue
            i += 1
            continue
        if line.startswith("#"):
            text_part = line[1:].strip()
            if (m := SUBSECTION_START_RE.match(text_part)) is not None:
                subsection = m.group(1)
                global_help = []
            elif SUBSECTION_END_RE.match(text_part) is not None:
                subsection = None
                global_help = []
            elif text_part.startswith("[GLOBAL]"):
                global_help.append(text_part[len("[GLOBAL]") :].strip())
            elif text_part.startswith("[NOGLOBAL]"):
                noglobal = True
                pending.append(text_part[len("[NOGLOBAL]") :].strip())
            elif text_part == SKIP_DOCS:
                skip_docs = True
            elif text_part == DO_NOT_EDIT:
                do_not_edit = True
            elif text_part.startswith("saltbox-lint"):
                pass
            elif text_part:
                pending.append(text_part)
            i += 1
            continue
        i += 1

    _apply_scopes(role, fields)
    instances_var = f"{role}_instances"
    instances_field = next((f for f in fields if f.name == instances_var), None)
    default_instances = (
        [str(v) for v in instances_field.value]
        if instances_field is not None and isinstance(instances_field.value, list)
        else []
    )
    return RoleDefaults(
        role=role,
        path=Path(path),
        fields=fields,
        sections=sections,
        instances_var=instances_var if instances_field is not None else None,
        default_instances=default_instances,
    )


def _raw_value(lines: list[str], start: int, end: int) -> str:
    chunk = lines[start:end]
    while chunk and (not chunk[-1].strip() or chunk[-1].startswith("#")):
        chunk.pop()
    return "\n".join(chunk)


def _apply_scopes(role: str, fields: list[Field]) -> None:
    names = {f.name for f in fields}
    role_prefix = f"{role}_role"
    for fld in fields:
        if fld.name == f"{role}_instances":
            fld.scope = "instances"
        elif fld.name.startswith(role_prefix + "_"):
            fld.scope = "role"
            fld.suffix = fld.name[len(role_prefix) :]
        elif fld.name.startswith(f"{role}_"):
            fld.scope = "instance-default"
            fld.suffix = fld.name[len(role) :]
        else:
            fld.scope = "global"
        if fld.hidden:
            continue
        if fld.name.endswith("_lookup"):
            fld.hidden, fld.hidden_reason = True, "lookup"
        elif (
            not fld.name.endswith(("_default", "_custom"))
            and f"{fld.name}_default" in names
            and f"{fld.name}_custom" in names
        ):
            fld.hidden, fld.hidden_reason = True, "aggregate"


def infer_type(name: str, value: Any, raw: str) -> str:
    """Type label for a default. Mirrors the docs generator's inference."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if value is None:
        return "string"
    text = str(value)
    if not JINJA_RE.search(text):
        return "string"
    for suffix, label in OVERRIDE_TYPES.items():
        if name.endswith(suffix):
            return label
    for suffix, label in EXACT_TYPES.items():
        if name.endswith(suffix):
            return label
    for filter_name, label in FILTER_TYPES.items():
        if re.search(rf"\|\s*{re.escape(filter_name)}\b", text):
            return label
    docker_match = re.search(r"_docker_([a-z_]+?)(?:_default|_custom)?$", name)
    if docker_match:
        option = docker_match.group(1)
        if option in DOCKER_LIST_SUFFIXES:
            return "list"
        if option in DOCKER_DICT_SUFFIXES:
            return "dict"
        if option in DOCKER_BOOL_SUFFIXES:
            return "bool"
        if option in DOCKER_INT_SUFFIXES:
            return "int"
    for suffix, label in SUFFIX_PATTERNS:
        if suffix in name:
            return label
    if re.search(r"\|\s*(combine|list|unique|reject|select|map)\b", text):
        return "list" if re.search(r"\|\s*(list|unique|reject|select|map)\b", text) else "dict"
    return "string"
