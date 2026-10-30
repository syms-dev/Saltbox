"""YAML helpers.

Two loaders: a round-trip loader that keeps comments and key order, used for
anything the engine writes back, and a plain loader for read-only data.
Saves are atomic and keep the existing file's mode and ownership, which
matters because sb tightens permissions on the config files.
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.constructor import DuplicateKeyError
from ruamel.yaml.nodes import MappingNode, Node, SequenceNode


def _rt() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.allow_duplicate_keys = True
    return yaml


def _safe() -> YAML:
    yaml = YAML(typ="safe", pure=True)
    yaml.allow_duplicate_keys = True
    return yaml


def load_text(text: str) -> Any:
    """Round-trip load YAML text. Returns ``None`` for an empty document."""
    return _rt().load(text)


def load_yaml(path: Path) -> Any:
    """Round-trip load a file. Missing file raises ``FileNotFoundError``."""
    return load_text(Path(path).read_text(encoding="utf-8"))


def load_plain(path: Path) -> Any:
    """Load a file into plain Python objects. Missing file raises ``FileNotFoundError``."""
    return _safe().load(Path(path).read_text(encoding="utf-8"))


def load_plain_text(text: str) -> Any:
    return _safe().load(text)


def dump_text(data: Any) -> str:
    buf = io.StringIO()
    _rt().dump(data, buf)
    return buf.getvalue()


def to_plain(value: Any) -> Any:
    """Convert ruamel containers into plain dicts, lists and scalars."""
    if isinstance(value, CommentedMap | dict):
        return {str(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, CommentedSeq | list | tuple):
        return [to_plain(v) for v in value]
    if isinstance(value, bool | int | float | str) or value is None:
        return value
    # ruamel scalar types (ScalarFloat, TaggedScalar, timestamps) collapse to str
    return str(value)


def save_yaml(path: Path, data: Any, *, header: str | None = None) -> None:
    """Write ``data`` atomically, keeping the existing mode and owner.

    ``header`` is prepended verbatim when the file does not exist yet, so new
    files can carry the same ``---`` and comments the defaults do.
    """
    path = Path(path)
    text = dump_text(data)
    if header and not path.exists():
        text = header.rstrip("\n") + "\n" + text
    if not text.startswith("---"):
        text = "---\n" + text
    write_atomic(path, text)


def write_atomic(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = uid = gid = None
    if path.exists():
        st = path.stat()
        mode, uid, gid = st.st_mode & 0o7777, st.st_uid, st.st_gid
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
            if os.geteuid() == 0 and uid is not None and gid is not None:
                os.chown(tmp, uid, gid)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def find_duplicate_keys(text: str) -> list[str]:
    """Return dotted paths of duplicated mapping keys, like ``sb validate-config``.

    Each entry reads ``path (appears N times)``.
    """
    yaml = _rt()
    try:
        root = yaml.compose(text)
    except DuplicateKeyError as error:  # pragma: no cover - allow_duplicate_keys is set
        return [str(error)]
    found: list[str] = []
    if root is not None:
        _walk_duplicates(root, "", found)
    return found


def _walk_duplicates(node: Node, path: str, found: list[str]) -> None:
    if isinstance(node, MappingNode):
        seen: dict[str, int] = {}
        for key_node, value_node in node.value:
            key = str(getattr(key_node, "value", key_node))
            current = f"{path}.{key}" if path else key
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                found.append(f"{current} (appears {seen[key]} times)")
            _walk_duplicates(value_node, current, found)
    elif isinstance(node, SequenceNode):
        for index, item in enumerate(node.value):
            _walk_duplicates(item, f"{path}[{index}]", found)


def get_path(data: Any, dotted: str) -> Any:
    """Read ``a.b.c`` from nested mappings. Raises ``KeyError`` when absent."""
    current = data
    for part in dotted.split("."):
        if not isinstance(current, dict | CommentedMap) or part not in current:
            raise KeyError(dotted)
        current = current[part]
    return current


def set_path(data: Any, dotted: str, value: Any) -> None:
    """Set ``a.b.c`` in nested mappings, creating intermediate maps."""
    parts = dotted.split(".")
    current = data
    for part in parts[:-1]:
        nxt = current.get(part) if isinstance(current, dict | CommentedMap) else None
        if not isinstance(nxt, dict | CommentedMap):
            nxt = CommentedMap()
            current[part] = nxt
        current = nxt
    current[parts[-1]] = value


def coerce_scalar(text: str) -> Any:
    """Turn a command line string into the YAML value it represents.

    Uses YAML 1.2 rules like sb and ruamel do, so ``yes``/``no`` stay strings
    (Ansible still reads them as booleans) while ``true``, ``12`` and
    ``[a, b]`` become a bool, an int and a list. Unparseable text is kept.
    """
    try:
        return load_plain_text(text)
    except Exception:
        return text
