"""The port registry Saltbox roles allocate from (``port-assignments.json``)."""

from __future__ import annotations

import json
from typing import Any

from ..layout import Layout


def read_port_assignments(layout: Layout) -> dict[str, Any]:
    path = layout.ports_file
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ValueError(f"cannot parse {path}: {error}") from error
    return data if isinstance(data, dict) else {}
