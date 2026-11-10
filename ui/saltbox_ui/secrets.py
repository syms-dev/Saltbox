"""Keep passwords, tokens and keys out of what the daemon sends to browsers.

Config files are shown with each secret replaced by a placeholder naming it,
``<hidden:user.pass>`` (in angle quotes). Saving text that still holds a placeholder puts the
saved value back, so editing a file never needs (or loses) its secrets.
Parsed data is masked the same way, and free text such as job logs and setup
instructions has known secret values replaced.

What counts as a secret is decided by the key's name: ``pass``, ``password``,
``token``, ``secret``, ``api``/``api_key``, ``private_key`` and the like, in
any case, so Gluetun's ``WIREGUARD_PRIVATE_KEY`` is covered as well as
``user.pass`` in accounts.yml.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

OPEN, CLOSE = "\u2039", "\u203a"  # single angle quotes, which no config value is made of
HIDDEN = f"{OPEN}hidden{CLOSE}"
PLACEHOLDER = re.compile(f"{OPEN}hidden:([^{CLOSE}\\n]+){CLOSE}")

SECRET_WORDS = (
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "apikey",
    "api_key",
    "private_key",
    "privatekey",
    "claim",
    "credential",
)
SECRET_NAMES = {"pass", "api", "key", "auth", "psk", "pin"}
MIN_SECRET_LENGTH = 6


def is_secret_key(key: object) -> bool:
    name = str(key).strip().strip("\"'").lower()
    if name in SECRET_NAMES or name.endswith(("_pass", "_key", "_pin")):
        return not name.endswith(("ssh_key", "_public_key", "publickey"))
    return any(word in name for word in SECRET_WORDS)


# -- YAML text ----------------------------------------------------------------------
_LINE = re.compile(
    r"""^(?P<indent>[ ]*)(?P<dash>-[ ]+)?(?P<key>"[^"]*"|'[^']*'|[^\s#:"'][^:#]*?)
        (?P<sep>[ ]*:[ ]+)
        (?P<value>"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^\s#|>&*!{\[][^#]*?)
        (?P<tail>[ ]+\#.*)?[ ]*$""",
    re.VERBOSE,
)
_KEY_ONLY = re.compile(r"^(?P<indent>[ ]*)(?:-[ ]+)?(?P<key>[^\s#:][^:#]*?)[ ]*:[ ]*(?:\#.*)?$")


def _walk(text: str) -> Iterable[tuple[int, str, re.Match[str] | None]]:
    """Each line with the dotted key path it sets (when it sets a scalar)."""
    stack: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    for number, line in enumerate(text.split("\n")):
        match = _LINE.match(line)
        parent = _KEY_ONLY.match(line) if match is None else None
        found = match or parent
        if found is None:
            yield number, "", None
            continue
        indent = len(found.group("indent")) + (
            2 if match is not None and match.group("dash") else 0
        )
        while stack and stack[-1][0] >= indent:
            stack.pop()
        key = found.group("key").strip().strip("\"'")
        path = ".".join([k for _, k in stack] + [key])
        if parent is not None:
            stack.append((indent, key))
            yield number, path, None
            continue
        seen[path] = seen.get(path, 0) + 1
        if seen[path] > 1:  # the same key twice (list items): keep each one apart
            path = f"{path}#{seen[path]}"
        yield number, path, match


def secret_values(text: str) -> dict[str, str]:
    """``{path: raw value}`` for every non-empty secret scalar in YAML text."""
    found: dict[str, str] = {}
    for _, path, match in _walk(text):
        if match is None or not is_secret_key(match.group("key")):
            continue
        value = match.group("value")
        if value.strip() in ("", '""', "''", "~", "null") or PLACEHOLDER.fullmatch(value.strip()):
            continue
        found[path] = value
    return found


def mask_text(text: str) -> str:
    """The YAML text with every secret value replaced by a placeholder naming it."""
    lines = text.split("\n")
    secrets = secret_values(text)
    for number, path, match in _walk(text):
        if match is None or path not in secrets:
            continue
        start, end = match.span("value")
        lines[number] = f"{lines[number][:start]}{placeholder(path)}{lines[number][end:]}"
    return "\n".join(lines)


def placeholder(path: str) -> str:
    return f"{OPEN}hidden:{path}{CLOSE}"


class UnknownPlaceholder(ValueError):
    pass


def unmask_text(text: str, saved: str) -> str:
    """Put the saved values back wherever the text still holds their placeholders."""
    secrets = secret_values(saved)

    def restore(match: re.Match[str]) -> str:
        path = match.group(1)
        if path not in secrets:
            raise UnknownPlaceholder(
                f"{placeholder(path)} does not match a saved secret; type the value instead"
            )
        return secrets[path]

    return PLACEHOLDER.sub(restore, text)


# -- parsed data and free text ------------------------------------------------------------
def mask_tree(value: Any, key: object = None) -> Any:
    """A copy of parsed YAML/JSON with secret-keyed scalars replaced by ``HIDDEN``."""
    if isinstance(value, dict):
        return {k: mask_tree(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_tree(v, key) for v in value]
    if key is not None and is_secret_key(key) and value not in (None, ""):
        return HIDDEN
    return value


def tree_secrets(value: Any, key: object = None) -> list[str]:
    """Every secret-keyed scalar in parsed data, as text."""
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in tree_secrets(v, k)]
    if isinstance(value, list):
        return [s for v in value for s in tree_secrets(v, key)]
    if key is not None and is_secret_key(key) and value not in (None, ""):
        return [str(value)]
    return []


class Redactor:
    """Replaces known secret values in free text (logs, instructions) with ``HIDDEN``."""

    def __init__(self, values: Iterable[str]):
        unique = {v.strip().strip("\"'") for v in values if v}
        self.values = sorted(
            (v for v in unique if len(v) >= MIN_SECRET_LENGTH), key=len, reverse=True
        )
        self._pattern = (
            re.compile("|".join(re.escape(v) for v in self.values)) if self.values else None
        )

    def __call__(self, text: str) -> str:
        if self._pattern is None or not text:
            return text
        return self._pattern.sub(HIDDEN, text)
