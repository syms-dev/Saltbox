# saltbox-ui

Engine, terminal UI and web UI for Saltbox. See `docs/ui/PLAN.md` at the
repository root for the design.

The package has two parts today:

- the engine (phase 0): reads, validates and writes Saltbox configuration,
  builds the app catalog from the playbooks and role defaults, runs `sb`, and
  reads runtime state. A JSON command line, `sbx`, exposes it for scripting.
- the TUI installer (phase 1): `saltbox-ui`, a wizard that takes a fresh
  Ubuntu server through preflight checks, account, DNS, apps, storage (rclone
  remotes through rclone's own question API, including headless OAuth) and the
  install itself, and resumes after the reboot preinstall may trigger.

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
  installer/       install plan (JSON, resumable), preflight checks, session
  rclone/          rclone's non-interactive config API as a question loop
  tui/             Textual app: step screens, rclone modal, shared widgets
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

## Installer

On a server that already ran the Saltbox bootstrap (`sb` and
`/srv/git/saltbox` present):

```
sudo -H pipx install /srv/git/saltbox/ui      # or: uv tool install
saltbox-ui
```

`saltbox-ui` re-executes itself through sudo when needed, keeping the
`SALTBOX_*` variables. Progress is saved to `/var/lib/saltbox-ui/install-plan.json`
after every step; start it again after a reboot or a dropped SSH session and
it offers to resume. `saltbox-ui --serve 0.0.0.0:8700` serves the same wizard
to a browser through textual-serve (install the `serve` extra); keep that
behind SSH port forwarding, it has no authentication of its own.

The same steps are scriptable:

```
sbx install preflight            # the checks the first screen shows
sbx install plan                 # the saved plan, secrets redacted
sbx install apply --validate     # write accounts.yml and friends from the plan
sbx install tags                 # what the install run would pass to sb
```

To try the wizard without touching a real server, point it at a checkout and a
fake `sb` (see `tests/conftest.py`), and set `SALTBOX_UI_NO_SUDO=1` so it does
not re-exec as root:

```
SALTBOX_UI_NO_SUDO=1 SALTBOX_REPO=$PWD/.. SALTBOX_APPDATA=/tmp/opt \
SALTBOX_UI_STATE=/tmp/state SB_BINARY=/tmp/fake-sb .venv/bin/saltbox-ui
```

The TUI tests drive every screen with Textual's pilot against a fake `sb` and
a fake `rclone` that speaks the config-create protocol.
