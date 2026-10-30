"""Tags sb has cached per repository (``cache.json``)."""

from __future__ import annotations

import json
from typing import Any

from ..layout import Layout


def cached_tags(layout: Layout) -> dict[str, dict[str, Any]]:
    """``{repo_path: {"commit": ..., "tags": [...]}}`` as sb stores it."""
    path = layout.cache_file
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
