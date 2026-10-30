import json
from pathlib import Path

import pytest

from saltbox_ui.cli import main
from saltbox_ui.layout import Layout


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip().startswith(("{", "[")) else out)


def test_layout_and_config(env_layout: Layout, capsys):
    code, data = run(capsys, "layout")
    assert code == 0 and data["repo"] == str(env_layout.repo)
    code, data = run(capsys, "config", "show", "accounts")
    assert data["source"] == "default"
    code, data = run(capsys, "config", "init", "accounts")
    assert data["created"] is True
    code, data = run(capsys, "config", "set", "accounts", "user.domain", "example.com")
    assert data["value"] == "example.com"
    code, data = run(capsys, "config", "validate", "accounts")
    assert code == 3
    assert any("user.email" in i["path"] for i in data["results"]["accounts"])
    run(capsys, "config", "set", "accounts", "user.email", "me@example.com")
    run(capsys, "config", "set", "accounts", "user.pass", "a-long-enough-password")
    code, data = run(capsys, "config", "validate", "accounts")
    assert code == 0 and data["ok"] is True


def test_inventory_and_catalog(env_layout: Layout, capsys, repo_root: Path):
    code, data = run(capsys, "inventory", "set", "sonarr_instances", "[sonarr, sonarr4k]")
    assert data["value"] == ["sonarr", "sonarr4k"]
    # the scratch repo has no roles; point the catalog at the real one for fields
    code, data = run(capsys, "inventory", "instances", "sonarr")
    assert data["instances"] == ["sonarr", "sonarr4k"]
    code, data = run(capsys, "catalog", "roles")
    assert any(r["role"] == "sonarr" for r in data)
    code, data = run(capsys, "catalog", "fields", "missing_role")
    assert code == 1


def test_catalog_fields_against_real_repo(
    monkeypatch: pytest.MonkeyPatch, repo_root: Path, tmp_path, capsys
):
    monkeypatch.setenv("SALTBOX_REPO", str(repo_root))
    monkeypatch.setenv("SALTBOX_APPDATA", str(tmp_path))
    monkeypatch.setenv("SALTBOX_UI_STATE", str(tmp_path / "state"))
    code, data = run(capsys, "catalog", "fields", "sonarr")
    assert code == 0
    assert data["instances_var"] == "sonarr_instances"
    assert all(not f["hidden"] for f in data["fields"])
    code, data = run(capsys, "catalog", "apps")
    assert any(a["role"] == "plex" for a in data)
    code, data = run(capsys, "catalog", "profiles")
    assert "saltbox_roles" in data


def test_run_dry_run_and_jobs(env_layout: Layout, fake_sb: Path, capsys):
    code, data = run(capsys, "run", "install", "core,plex", "--skip-tags", "settings", "--dry-run")
    assert data["command"] == [str(fake_sb), "install", "core,plex", "--skip-tags", "settings"]
    code, data = run(capsys, "run", "install", "core")
    assert code == 0 and data["status"] == "succeeded"
    code, data = run(capsys, "run", "jobs")
    assert len(data) == 1
    code, data = run(capsys, "run", "status")
    assert data["running"] is None
    code, data = run(capsys, "state", "facts")
    assert data["roles"] == []
    code, data = run(capsys, "state", "mounts")
    assert isinstance(data, list)
