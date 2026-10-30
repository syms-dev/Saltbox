"""Role facts stored by the ``saltbox_facts`` module.

One INI file per role under ``<appdata>/saltbox/<role>.ini``, one section per
instance, keys such as ``api_key`` or ``token``. Parsed with the same
ConfigParser settings the module uses so values round-trip identically.
"""

from __future__ import annotations

import configparser
from pathlib import Path
from typing import Any

from ..layout import Layout

SECRET_KEYS = {"api_key", "apikey", "token", "password", "pass", "secret", "key"}


class CaseSensitiveParser(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return str(optionstr)


def _parser() -> CaseSensitiveParser:
    return CaseSensitiveParser(
        interpolation=None,
        comment_prefixes=("#",),
        inline_comment_prefixes=None,
        default_section="DEFAULT",
        delimiters=("=",),
        empty_lines_in_values=False,
    )


def read_facts_file(path: Path) -> dict[str, dict[str, str]]:
    parser = _parser()
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            parser.read_file(handle)
    except configparser.Error as error:
        raise ValueError(f"cannot parse facts file {path}: {error}") from error
    return {section: dict(parser[section]) for section in parser.sections()}


def read_role_facts(layout: Layout, role: str) -> dict[str, dict[str, str]]:
    return read_facts_file(layout.facts_dir / f"{role}.ini")


def list_fact_roles(layout: Layout) -> list[str]:
    if not layout.facts_dir.exists():
        return []
    return sorted(p.stem for p in layout.facts_dir.glob("*.ini"))


def read_all_facts(layout: Layout, *, redact: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for role in list_fact_roles(layout):
        facts = read_role_facts(layout, role)
        if redact:
            facts = {
                instance: {k: redact_value(k, v) for k, v in values.items()}
                for instance, values in facts.items()
            }
        result[role] = facts
    return result


def redact_value(key: str, value: str) -> str:
    if key.lower() in SECRET_KEYS and value:
        return value[:4] + "…" if len(value) > 8 else "…"
    return value
