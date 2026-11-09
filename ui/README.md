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
- the daemon and web face (phase 2): `saltbox-uid`, a FastAPI service with
  the one-at-a-time job queue and a WebSocket log stream, and `web/`, a React
  app served by the daemon at `https://saltbox.<domain>` behind Traefik and
  Authelia: overview, apps, jobs, config editor.

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
  daemon/          FastAPI app, routes, job manager, systemd unit, Traefik route
  cli.py           sbx, JSON output
web/               React + TypeScript app (Vite), built into web/dist
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
`/srv/git/saltbox` present), point the checkout at the fork and install the
package. The bootstrap makes a shallow clone that only tracks `master`, so
widen the fetch refspec first; without it the branch is fetched but never
gets an `origin/` name and the checkout fails. The wider refspec also lets
`sb update` follow the fork's branch afterwards.

```
cd /srv/git/saltbox
sudo git remote set-url origin https://github.com/syms-dev/Saltbox.git
sudo git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
sudo git fetch origin claude/saltbox-gui-tui-bxul3c
sudo git checkout -B claude/saltbox-gui-tui-bxul3c origin/claude/saltbox-gui-tui-bxul3c

sudo apt install -y pipx
sudo PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install --editable /srv/git/saltbox/ui
sudo saltbox-ui
```

`PIPX_HOME` and `PIPX_BIN_DIR` put the commands in `/usr/local/bin`, which is
on sudo's path. A plain `sudo -H pipx install` puts them in
`/root/.local/bin`, which is not. `--editable` makes the installed commands
run the code in the checkout, so updating the checkout updates the UI too.
Tested on Ubuntu 26.04 with Python 3.14.

### Updating

Keep using `sb update`. It fetches the checkout's current branch and resets
to it (`git reset --hard @{u}`), so with the branch tracking the fork it
pulls the fork, never saltyorg. When it asks whether to reset to `master`,
answer `n`; answering `y` moves the checkout back to upstream Saltbox and
the UI disappears. Run without a terminal, as the daemon's update job does,
it stays on the current branch without asking. After an update that changes
the UI's dependencies, refresh them with:

```
sudo PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install --force --editable /srv/git/saltbox/ui
```

Upstream Saltbox changes reach the server only through the fork: sync the
fork's `master` with saltyorg on GitHub, then merge `master` into the UI
branch.

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

## Daemon and web app

The daemon runs as root under systemd. It listens on 127.0.0.1 and on the
Docker bridge address (172.19.0.1, which Traefik knows as
`host.docker.internal`), plus a root-only Unix socket. Every TCP request must
carry a bearer token kept in `/var/lib/saltbox-ui/api-token`; the Traefik
route adds that header after Authelia has authenticated the person, so a
browser never sees the token and a local process without root cannot drive
the daemon.

Enable it from the installer's last screen, or by hand:

```
cd /srv/git/saltbox/ui/web && npm ci && npm run build     # needs node 22
sudo sbx daemon enable --web /srv/git/saltbox/ui/web/dist
```

That writes `/opt/traefik/saltbox-ui.yml` (file provider, watched by
Traefik), `/etc/systemd/system/saltbox-ui.service`, and starts it. The app
answers at `https://saltbox.<domain>` once Traefik has a certificate. The API
is documented at `/api/docs` on the daemon; `sbx daemon token` prints the
token for curl.

Development: start `saltbox-uid --no-token --no-uds --port 8701` against a
checkout (same `SALTBOX_*` variables as above) and `npm run dev` in `web/`;
Vite proxies `/api` to the daemon.
