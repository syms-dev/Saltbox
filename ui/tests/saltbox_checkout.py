"""Where the tests find Saltbox itself.

The suite uses the real playbook, schemas, config defaults and role defaults as
fixtures. They come from, in order: ``SALTBOX_CHECKOUT``; the repository this
directory sits in, when that is a Saltbox checkout; ``tests/.saltbox``, which
``scripts/fetch-saltbox.sh`` fills with the pinned upstream commit.
"""

from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _is_saltbox(path: Path) -> bool:
    return (path / "saltbox.yml").is_file() and (path / "roles").is_dir()


def saltbox_checkout() -> Path:
    env = os.environ.get("SALTBOX_CHECKOUT")
    candidates = ([Path(env)] if env else []) + [HERE.parents[1], HERE / ".saltbox"]
    for candidate in candidates:
        if _is_saltbox(candidate):
            return candidate.resolve()
    raise RuntimeError(
        "no Saltbox checkout for the tests: run scripts/fetch-saltbox.sh, "
        "or set SALTBOX_CHECKOUT to a clone of https://github.com/saltyorg/Saltbox"
    )
