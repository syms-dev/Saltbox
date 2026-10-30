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
    for role in ("main_tags", "media_server", "download_clients", "download_indexers"):
        source = REPO_ROOT / "roles" / role / "defaults" / "main.yml"
        if source.exists():
            target = repo / "roles" / role / "defaults" / "main.yml"
            target.parent.mkdir(parents=True)
            shutil.copy(source, target)
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


FAKE_RCLONE = r'''#!/usr/bin/env python3
"""A stand-in rclone: enough of the config API for the installer tests.

The ``--config`` path is used as a JSON store of remotes. ``config create``
for any type asks three questions: client_id (free text), config_is_local
(exclusive bool) and config_token (with an ``rclone authorize`` hint).
"""
import json
import os
import sys

args = sys.argv[1:]
config = None
if "--config" in args:
    i = args.index("--config")
    config = args[i + 1]
    del args[i : i + 2]
log = os.environ.get("FAKE_RCLONE_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(json.dumps(args) + "\n")


def load():
    try:
        with open(config) as fh:
            return json.load(fh)
    except (OSError, ValueError, TypeError):
        return {}


def save(data):
    with open(config, "w") as fh:
        json.dump(data, fh)


def out(data):
    print(json.dumps(data))


QUESTIONS = {
    "": ("q1", {"Name": "client_id", "Help": "OAuth client id", "Default": "", "Type": "string"}),
    "q1": (
        "q2",
        {
            "Name": "config_is_local",
            "Help": "Use web browser to automatically authenticate?",
            "Default": True,
            "Type": "bool",
            "Exclusive": True,
            "Examples": [{"Value": "true", "Help": "Yes"}, {"Value": "false", "Help": "No"}],
        },
    ),
    "q2": (
        "q3",
        {
            "Name": "config_token",
            "Help": "For this to work, you will need rclone available on a machine that "
            "has a web browser available.\n\n"
            "rclone authorize \"drive\" \"eyJzY29wZSI6ImRyaXZlIn0\"\n\n"
            "Then paste the result.",
            "Default": "",
            "Type": "string",
            "Required": True,
        },
    ),
}

if not args:
    sys.exit(1)
cmd = args[0]
if cmd == "version":
    print("rclone v1.70.0-fake")
elif cmd == "listremotes":
    for name in load():
        print(f"{name}:")
elif cmd == "lsjson":
    remote = args[-1].split(":", 1)[0]
    data = load()
    dirs = data.get(remote, {}).get("dirs", [])
    out([{"Name": d, "IsDir": True, "Path": d} for d in dirs])
elif cmd == "mkdir":
    remote, path = args[1].split(":", 1)
    data = load()
    data.setdefault(remote, {"type": "drive", "dirs": []}).setdefault("dirs", [])
    top = path.split("/", 1)[0]
    if top not in data[remote]["dirs"]:
        data[remote]["dirs"].append(top)
    save(data)
elif cmd == "config" and args[1] == "dump":
    out({name: {"type": values.get("type", "drive")} for name, values in load().items()})
elif cmd == "config" and args[1] == "providers":
    out(
        [
            {"Name": "drive", "Description": "Google Drive", "Options": []},
            {"Name": "sftp", "Description": "SSH/SFTP", "Options": []},
        ]
    )
elif cmd == "config" and args[1] == "delete":
    data = load()
    data.pop(args[2], None)
    save(data)
elif cmd == "config" and args[1] == "create":
    name, rtype = args[2], args[3]
    state = ""
    result = None
    if "--state" in args:
        state = args[args.index("--state") + 1]
        result = args[args.index("--result") + 1]
    if state == "q3":
        if not result:
            out({"State": "q3", "Option": QUESTIONS["q2"][1], "Error": "token is required"})
            sys.exit(0)
        data = load()
        data[name] = {"type": rtype, "dirs": [], "token": result}
        save(data)
        out({"State": "", "Option": None, "Error": ""})
        sys.exit(0)
    if state == "q1" and result == "bad":
        print("invalid value for client_id", file=sys.stderr)
        sys.exit(1)
    next_state, option = QUESTIONS[state]
    out({"State": next_state, "Option": option, "Error": ""})
else:
    print(f"fake rclone: unknown command {args}", file=sys.stderr)
    sys.exit(1)
'''


@pytest.fixture
def fake_rclone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in ``rclone`` speaking the non-interactive config protocol."""
    path = tmp_path / "bin" / "rclone"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FAKE_RCLONE)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("FAKE_RCLONE_LOG", str(tmp_path / "rclone.log"))
    return path
