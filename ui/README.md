# saltbox-ui

An unofficial installer and web dashboard for [Saltbox](https://github.com/saltyorg/Saltbox).

It sits on top of an unmodified Saltbox install. It reads Saltbox's own
playbook, schemas and role defaults, and installs, updates and backups go
through Saltbox's `sb` command, so Saltbox's own checks and locking still
apply. It never calls Ansible itself and it does not change any Saltbox file
except the config files you edit through it.

A few things `sb` has no command for are done directly, each only when you
ask: starting, stopping, restarting and removing containers with Docker;
deleting an uninstalled app's folder; restarting the server; and settings made
through the apps' own APIs (Connect apps, seeding limits).

**This is not part of Saltbox and the Saltbox team does not support it.** If
something here breaks, open an issue in this repository, not in Saltbox's
Discord or issue tracker.

I wanted to install and look after my own Saltbox server without living in a
terminal, so I built this, for fun, with an AI coding assistant (see
[How it was built](#how-it-was-built)).

## What it does

**Terminal installer** (`saltbox-ui`): a wizard that takes a fresh Ubuntu
server through preflight checks, account and domain, DNS and certificates,
choosing apps, storage (rclone remotes, including headless sign-in), linking
Plex, and the install itself. It saves progress after every step and resumes
after a reboot or a dropped SSH session.

**Web app** (`https://saltbox.<your domain>`, behind Traefik and Authelia):

- **Home** leads with what needs you, each item with the button that fixes it:
  restart an unhealthy app, start a stopped one, apply updates, open a config
  file with errors, retry a failed job, start the VPN, restart the server
  when Ubuntu's updates need it (it says which). Then media at a glance:
  the VPN (public IP, forwarded port, what is routed through it), downloads in
  qBittorrent and SABnzbd (and how much keeps seeding after it finished), what
  is playing on Plex and what Sonarr and Radarr expect this week; a launcher for your apps; updates, storage and activity.
- **Apps**: installed apps with health, update and restart buttons, and a
  Discover tab to install anything in the Saltbox and Sandbox catalogs. What
  runs as part of Saltbox itself (Traefik, Authelia) is listed too, marked
  Core, so its updates are not missed. An app you no longer use can be
  uninstalled: its containers are removed, and its settings folder too if you
  say so. Each app
  has a page with its containers (restart, stop, start, CPU and memory), live
  logs, inventory overrides and role defaults, docs and links.
- **Activity**: every job with a live log. A failed job says which task failed
  and why, and can be run again.
- **System**: CPU and memory, with every container sortable by name, CPU or
  memory; errors that keep recurring in the apps' logs, one card each, with
  what the known ones mean, advice that depends on whether the server has
  cloud storage, and a fix button where the fix is safe; each drive and pool
  once; with Scrutiny installed, every drive's health, temperature and age,
  and which attribute a failing one fails on (it goes to the top of Home).
  Drive and log issues can be dismissed; a dismissed drive comes back if
  another attribute starts failing. With Claude Code installed on the server,
  any log issue can be put to Claude for an explanation (see
  [Explanations by Claude](#explanations-by-claude));
  mounts and Saltbox services; Tailscale (and opening this app over it);
  backups (`sb install backup` on demand); Saltbox's own version and `sb update`,
  which shows the update's announcements with the job and waits for your yes or
  no before it runs migrations.
- **Automation**: alerts to your phone through Apprise (the notification tool
  Saltbox already installs; `apprise:` in accounts.yml is the default address)
  when an app turns unhealthy or stops, a job fails, a disk passes 90%, updates
  arrive or the VPN has a problem; and nightly maintenance that updates apps
  with new images (Traefik and Authelia included), except the ones you
  exclude, and sends one summary. It does
  not update Saltbox itself: `sb update` is made to be run by a person.
- **Connect apps**: quality profiles through Recyclarr (TRaSH Guides profiles,
  written to `/opt/recyclarr` with keys read from the apps), with a count of
  how many shows and films use each profile and a button to move them all onto
  a synced one (a sync creates profiles; it assigns nothing); then the
  post-install wiring the Saltbox app docs describe: download clients, root
  folders, Prowlarr sync, FlareSolverr, Autoscan, Plex libraries and settings.
  A Seeding card shows the finished torrents still seeding in qBittorrent and
  sets the ratio and time limits that stop them, which is what lets Sonarr and
  Radarr remove them.
  Steps that must be done by hand in Bazarr and Seerr are checked from those
  apps' settings files.
- **Config**: the YAML files `sb` reads, with the same validation as
  `sb validate-config`.
- Search with Ctrl+K (⌘K) or `/` to open any app, page or action.
- When the server stops answering (a reboot, Traefik or Authelia being
  recreated) the page waits, reconnects by itself, signs in again if it has
  to, and after a boot shows the containers coming back.

A JSON command line, `sbx`, exposes the same engine for scripting.

## Status: what has and has not been checked

Version 0.2.0. Treat it as a beta.

| Check | Result |
| --- | --- |
| Python tests (pytest) | 337 tests; pass on Python 3.12 and 3.14 |
| Web unit tests (Vitest) | 84 tests pass |
| End-to-end tests (Playwright, Chromium) | 66 tests pass: every flow on desktop, every page at phone and tablet width, failing on any console error |
| Package | CI builds the wheel, installs it in a clean environment and loads the web app from it |
| Real servers | **One**: Ubuntu 26.04, Python 3.14, local drives pooled with mergerfs, Plex, qBittorrent behind Gluetun (ProtonVPN) |

The end-to-end tests run the real daemon and web app against a throwaway box
where only `sb`, `docker`, `tailscale`, `apprise`, the image registry and the
apps' HTTP APIs are faked (`tests/e2e_box.py`). That proves the UI and daemon
work together; it does not prove they match every real server.

They do not. On the one real server, these bugs got past the tests and were
found by using it:

- installs from the web app failed because systemd starts services without
  `HOME`, and because git refuses a repository owned by another user;
- qBittorrent 5.1 answers a successful login with 204, not "Ok.";
- Plex ignores writes to a library's `/prefs` endpoint;
- a VPN warning fired because Docker records `container:<id>`, not
  `container:<name>`, for apps inside Gluetun's network;
- Autoheal was missing from the app list because it keeps no folder in `/opt`;
- `sb update` refuses to run without a terminal, shows announcements in a
  full-screen viewer that waits for a key, and asks whether to run migrations.
  The stand-in for `sb` did none of that;
- new images for Traefik and for the Redis that Authelia runs were counted on
  Home until the apps list loaded, then dropped, because no listed app owned
  those containers.

Each is fixed and now has a test. Expect more of the same on setups unlike
that one. **Not yet run on any real server:**

- an `sb update` that brings announcements or asks about migrations. A plain
  `sb update` has run from the web app on the real server; the announcement
  and migration handling was written from sb's source code (`cmd/update.go`,
  `saltbox/announcements.go`) and is tested against a stand-in that behaves the
  same way at the terminal;
- uninstalling an app, and restarting the server from the web app;
- reconnecting after a real reboot or a real Traefik restart (tested by making
  the daemon unreachable in a browser test, not by restarting anything);
- the fix that creates Autoscan's anchor file;
- explanations by Claude (the command line and its flags come from Claude
  Code's documentation; it is tested against a stand-in, not the real CLI);
- the Saltbox UI update button (tested against a local git repository and a
  stand-in for npm; it has not updated a real install);
- moving shows and films onto a synced quality profile (the editor calls come
  from Sonarr's and Radarr's source; tested against stand-ins);
- drive health from Scrutiny (written from Scrutiny's source and tested against
  a stand-in for its API);
- the log problem finder. Its two app-specific explanations (Autoscan's anchor
  file, Bazarr and disc images) come from log lines on the real server and are
  tested against those lines, but it has not run there;
- the seeding limits (written from qBittorrent's API documentation and
  Sonarr's source, and tested against a stand-in for qBittorrent);
- installing this package from a release wheel (the real server runs it from a
  source checkout);
- the admin check behind a real Traefik and Authelia (tested with the headers
  they send, and against Traefik's source);
- cloud storage through the rclone wizard;
- Ubuntu 22.04 and 24.04;
- Jellyfin or Emby in place of Plex, and authentik in place of Authelia;
- more than one instance of an app (`sonarr4k` and the like);
- nightly maintenance, Back up now, and access over Tailscale.

If you try one of these, an issue saying how it went is useful either way.

## Install

You need a server that has run Saltbox's own dependency script, so `sb` and
`/srv/git/saltbox` exist: see the install section of the
[Saltbox docs](https://docs.saltbox.dev).
For a new server, stop after that script and let the wizard do the rest. For a
server that already runs Saltbox, nothing else is needed.

Install the wheel from this repository's Releases page with pipx:

```
sudo apt install -y pipx
V=0.2.0
sudo PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install \
  "https://github.com/syms-dev/saltbox-ui/releases/download/v$V/saltbox_ui-$V-py3-none-any.whl"
```

`PIPX_HOME` and `PIPX_BIN_DIR` put the commands in `/usr/local/bin`, which is
on sudo's path. The wheel carries the built web app, so the server needs no
Node.

Then, on a new server, run the installer:

```
sudo saltbox-ui
```

and on a server that already runs Saltbox, switch on the web app:

```
sudo sbx daemon enable
```

That writes a Traefik route (`/opt/traefik/saltbox-ui.yml`), a systemd unit
(`saltbox-ui.service`) and starts it. The app answers at
`https://saltbox.<your domain>` once Traefik has a certificate.

**Updating:** the System page shows when a newer Saltbox UI is available and
has a button that installs it (the newest release wheel, or `git pull` and a
rebuild when it runs from a source checkout) and restarts the daemon; the page
reloads itself on the new version. By hand: install the newer wheel with
`pipx install --force` and run `sudo systemctl restart saltbox-ui`. Saltbox
itself keeps updating with `sb update`, from the terminal or the System page.

**Removing:** `sudo sbx daemon disable` stops the service and removes its
systemd unit, Traefik route, the VPN port-sync timer and the Tailscale address.
Add `--purge` to also delete `/var/lib/saltbox-ui` (API token, job logs, alert
and maintenance settings). Then `sudo PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx uninstall saltbox-ui`.
Saltbox, its config and your apps are not touched.

## Security model

The daemon runs as root, because `sb` does. That makes who can reach it the
whole question.

- It listens on 127.0.0.1, on the Docker bridge address Traefik reaches it by,
  and on two root-only Unix sockets. Every TCP request, HTTP or WebSocket, must
  carry a bearer token kept in `/var/lib/saltbox-ui/api-token` (mode 0600).
  Traefik adds it after single sign-on, so a browser never holds the token.
- **Only the Saltbox admin gets in through Traefik.** The daemon reads the
  `Remote-User` header Authelia returns (or `X-authentik-username`) and lets in
  only the user from accounts.yml or a member of the `admins` group. Traefik
  deletes any copy of those headers a client sends. Other single-sign-on users
  are refused, and so is a request an SSO bypass rule let through without
  signing in. `SALTBOX_UI_ADMIN_CHECK=off` turns this off.
- Requests that change anything are refused when a browser says another site
  started them, so a page on a sibling subdomain cannot start jobs.
- **Secrets stay on the server.** Config files are shown with placeholders
  such as `‹hidden:user.pass›`, which are put back when you save; known
  passwords, tokens and API keys are replaced in job logs, container logs and
  setup instructions. "Show secrets" reveals them on request.
- Job records and logs are readable by root only.
- **Over Tailscale** (optional): `tailscale serve` proxies port 8443 of the
  server's tailnet address to one of the Unix sockets, and the daemon lets in
  only the Tailscale account that owns the server, refusing other tailnet users
  and tagged devices. It needs MagicDNS and HTTPS certificates enabled in the
  Tailscale admin console.

### Explanations by Claude

Each issue found in the logs has an "Ask Claude" button once
[Claude Code](https://code.claude.com/docs/en/setup) is installed on the server
and signed in for the Saltbox user (`claude auth login`, over SSH). Pressing it
shows what will be sent and asks first.

- **What is sent:** the error and about 25 log lines around it, to Anthropic.
  Passwords and keys this app knows are masked first; file names, addresses and
  anything else in those lines are not.
- **What Claude can do:** answer. It is run with every tool switched off, as
  the Saltbox user rather than root, in an empty folder. Its answer is shown as
  text and nothing in it is run.
- **Whose account:** whatever Claude Code on the server is signed in with, a
  Claude plan or an API key. This app does not sign you in and never sees a
  credential. Anthropic's Agent SDK documentation says that, unless approved,
  third-party developers may not offer claude.ai login or its rate limits for
  their products, and to use API keys instead. If you are unsure how that
  applies to you, sign Claude Code in with an API key.

A security review of the code found and fixed: the job log WebSocket skipping
the token check; job logs readable by any local user; and every single-sign-on
user being trusted. If you find something else, please open an issue.

## Development

```
scripts/fetch-saltbox.sh        # the pinned Saltbox commit the tests read, into tests/.saltbox
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev,docker]"
.venv/bin/ruff check . && .venv/bin/pytest

cd web
npm ci
npm test                        # unit tests
npm run e2e                     # builds the app, starts tests/e2e_box.py, runs e2e/*.spec.ts
```

`python -m tests.e2e_box --port 8790 --token dev` (from the repository root)
starts the same throwaway box to click around in, after `npm run build`.

Point the engine at a Saltbox checkout instead of a live install with
`SALTBOX_REPO`, `SALTBOX_APPDATA`, `SALTBOX_UI_STATE` and `SB_BINARY`:

```
SALTBOX_REPO=$PWD/tests/.saltbox .venv/bin/sbx catalog apps | head
```

```
saltbox_ui/
  layout.py        paths, mirroring sb's layout, overridable by environment
  yamlio.py        comment-preserving YAML load and save
  schema/          port of sb's YAML schema validator
  config/          the config files and the inventory
  catalog/         playbook roles and tags, role defaults parser, app catalog
  runner.py        sb command builder and streaming job runner with a lock
  state/           containers, image and Saltbox updates, host, Tailscale, backups
  installer/       install plan (resumable), preflight checks, session
  rclone/          rclone's non-interactive config API as a question loop
  appsetup/        post-install wiring of the apps through their own APIs
  tui/             the Textual installer
  daemon/          FastAPI app, routes, jobs, alerts and maintenance, systemd, Traefik
  secrets.py       masking of secrets in what the daemon sends
  media.py         VPN, downloads, Plex sessions, calendar
  recyclarr.py     Recyclarr config from chosen profiles
  cli.py           sbx
web/               React and TypeScript app (Vite); e2e/ holds the Playwright suite
tests/             pytest suite; e2e_box.py is the throwaway box
scripts/           fetch-saltbox.sh; build_catalog.py (app metadata from the Saltbox docs)
```

New pages get a case in `web/e2e/functional.spec.ts` and an entry in the page
list of `web/e2e/layout.spec.ts`.

Releases: bump `version` in `pyproject.toml`, tag `v<version>` and push the
tag. The Release workflow builds the wheel with the web app inside and attaches
it to a GitHub release.

## How it was built

Almost all of this code was written by Claude (Anthropic's AI model),
directed and tested by me on my own server. That is a reason to read the Status
section above before trusting it, not a selling point. What was done about it:
automated tests at three levels, run in CI on every push; a security review,
with its findings fixed; every bug found on the real server reproduced in a
test before it was fixed; and a list, above, of what has not been tried.

## License

GPL-3.0-only, the same license as Saltbox. The app catalog
(`saltbox_ui/catalog/data/apps.json`) is generated from the Saltbox
documentation. Saltbox is the work of the saltyorg contributors; this project
only drives it.
