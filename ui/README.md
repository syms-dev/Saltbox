# saltbox-ui

Engine, terminal UI and web UI for Saltbox. See `docs/ui/PLAN.md` at the
repository root for the design.

Phase 0 (this directory today) is the engine only: a Python package that
knows how to read, validate and write Saltbox configuration, build the app
catalog from the playbooks and role defaults, run `sb`, and read runtime state.
A JSON command line, `sbx`, exposes it for scripting and testing.

The package never calls Ansible directly. Every playbook run goes through the
upstream `sb` binary so its venv handling, tag validation and locking are
inherited unchanged.

## Layout

```
saltbox_ui/
  layout.py        paths, mirrors sb-go's layout package, env overridable
  yamlio.py        comment-preserving YAML load, save, duplicate key check
  schema/          port of sb's YAML schema validator and built-in validators
  config/          the six config files plus the inventory
  catalog/         playbook roles and tags, role defaults parser, app catalog
  runner.py        sb command builder and streaming job runner with a lock
  state/           facts, ports, mounts, containers, host, MOTD, tag cache
  cli.py           sbx, JSON output
tests/             pytest suite using the real roles as fixtures
scripts/           catalog data builder (reads a docs repo checkout)
```

## Development

```
cd ui
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev,docker]"
.venv/bin/ruff check . && .venv/bin/pytest
```

Point the engine at a checkout instead of a live install with environment
variables: `SALTBOX_REPO`, `SALTBOX_APPDATA`, `SB_BINARY`.

```
SALTBOX_REPO=$PWD/.. .venv/bin/sbx catalog apps | head
SALTBOX_REPO=$PWD/.. .venv/bin/sbx catalog fields sonarr
SALTBOX_REPO=$PWD/.. .venv/bin/sbx config validate
```
