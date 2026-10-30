from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import pytest

from saltbox_ui.layout import Layout

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def repo_layout(tmp_path: Path) -> Layout:
    """The real repository checkout with scratch appdata and state."""
    return Layout(
        repo=REPO_ROOT,
        appdata=tmp_path / "opt",
        sb_binary=tmp_path / "bin" / "sb",
        rclone_binary=tmp_path / "bin" / "rclone",
        state_dir=tmp_path / "state",
    )


@pytest.fixture
def scratch_repo(tmp_path: Path) -> Path:
    """A writable copy of the parts of the repo the config layer needs."""
    repo = tmp_path / "saltbox"
    repo.mkdir()
    shutil.copytree(REPO_ROOT / "schema", repo / "schema")
    shutil.copytree(REPO_ROOT / "defaults", repo / "defaults")
    (repo / "inventories" / "host_vars").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "saltbox.yml", repo / "saltbox.yml")
    return repo


@pytest.fixture
def scratch_layout(scratch_repo: Path, tmp_path: Path) -> Layout:
    return Layout(
        repo=scratch_repo,
        appdata=tmp_path / "opt",
        sb_binary=tmp_path / "bin" / "sb",
        rclone_binary=tmp_path / "bin" / "rclone",
        state_dir=tmp_path / "state",
    )


@pytest.fixture
def fake_sb(tmp_path: Path) -> Path:
    """A stand-in ``sb`` that echoes its arguments and honours FAKE_SB_EXIT."""
    path = tmp_path / "bin" / "sb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '#!/bin/sh\necho "sb args: $*"\necho "stderr line" >&2\nexit "${FAKE_SB_EXIT:-0}"\n'
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def env_layout(scratch_layout: Layout, monkeypatch: pytest.MonkeyPatch) -> Layout:
    monkeypatch.setenv("SALTBOX_REPO", str(scratch_layout.repo))
    monkeypatch.setenv("SALTBOX_APPDATA", str(scratch_layout.appdata))
    monkeypatch.setenv("SB_BINARY", str(scratch_layout.sb_binary))
    monkeypatch.setenv("SALTBOX_UI_STATE", str(scratch_layout.state_dir))
    monkeypatch.setenv("RCLONE_BINARY", str(scratch_layout.rclone_binary))
    os.environ.pop("FAKE_SB_EXIT", None)
    return scratch_layout
