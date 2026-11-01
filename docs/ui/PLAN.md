# Saltbox UI plan (draft 1)

Goal: a web GUI and a terminal UI for Saltbox. An installer that replaces
hand-editing YAML over SSH, and a management console for everything after.
Built on top of the existing Saltbox machinery (`sb`, playbooks, schemas,
role defaults, facts), never beside it.

Status: draft, waiting on decisions listed at the end. A visual version of
this plan with mockups was shared as a page in the planning session.

## What the docs and source confirmed

- `sb` is Go (`saltyorg/sb-go`, Cobra plus Charm). It re-launches as root and
  already contains small TUIs (`sb edit`, `sb fact`). Commands: install,
  update, list, validate-config, edit, fact, docker, logs, motd, diag, bench,
  branch, restore, reinstall-*, hidden `setup`.
- Install is: bootstrap one-liner (`sb setup`), edit accounts/settings/
  adv_settings, `sb validate-config`, `sb install preinstall` (creates the
  user, may reboot), log in as that user, rclone setup, `sb install
  saltbox|mediabox|feederbox|core`, reboot, per-app manual setup.
- Config: six YAML files with typed schemas in `schema/` that `sb` validates
  (including live Cloudflare and Docker Hub credential checks), plus a
  free-form inventory `inventories/host_vars/localhost.yml` checked only for
  duplicate keys.
- Role defaults are sectioned, commented and carry directives that the docs
  generator (`saltyorg/docs-automation`, Go) parses into typed settings. This
  is the basis for generated settings forms.
- Runtime state on disk: INI facts under `/opt/saltbox`, `saltbox.fact` host
  facts, `port-assignments.json`, Docker controller on 127.0.0.1:3377,
  tag cache in `cache.json`, MOTD config listing app URLs and keys.
- Nothing is reachable by IP and port. Apps live behind Traefik and Authelia.
  Host services are published through Traefik's file provider.
- `sb update` does `git fetch` + `git reset --hard origin/<branch>`;
  `sb setup` clones the hard-coded saltyorg URL. A fork must repoint the
  remote or anything it adds to `/srv/git/saltbox` is lost on update.
- Upstream position (prerequisites page): "There is no GUI and there are no
  plans to add one."

## Architecture

One engine, three faces.

- Faces: web app (React, served at `saltbox.<domain>` behind Traefik and
  Authelia), TUI (Textual, over SSH), and a small JSON CLI for scripting and
  tests.
- Engine (Python): config service (load, validate, save with comments kept),
  catalog (saltbox.yml, sandbox.yml, role defaults, docs frontmatter),
  settings schema (role defaults parsed into typed fields with role and
  instance scope), runner (job queue, one at a time, streams `sb` output,
  keeps history), state (containers, mounts, facts, ports, URLs,
  credentials, updates), rclone service (drives rclone's non-interactive
  config API).
- Daemon: `saltbox-ui.service`, root, FastAPI on a Unix socket plus
  127.0.0.1 port, WebSocket job streams. Both faces use it. Jobs survive a
  dropped SSH session.
- Existing Saltbox stays untouched: `sb`, playbooks, Docker controller,
  Traefik, Authelia, facts.

Chicken and egg: on a fresh box there is no domain, Traefik or Authelia, so
the TUI owns install phases one through five. The installer's last step
enables the web face and prints its URL.

## Web UI style options

- A. App store (CasaOS, Umbrel): tiles and one-click install. Friendly, weak
  for day-two work.
- B. Admin console (Cockpit, Proxmox): dense tables, one row per instance.
  Scales well, less inviting.
- C. Config-first (Dockge): inventory always visible with a form writing
  into it and a diff before every run. Trusted by experienced users, too
  much for a first install.
- D. Hybrid (recommended): overview that leads with what needs attention,
  tiles for discovery plus a table for installed instances, app pages with a
  generated settings form beside the raw inventory editor, jobs as a
  first-class area with live output and history, per-app setup checklists.

## TUI options

- Installer: a wizard in the style of Ubuntu's text installer in all cases.
- Shape 1: panes (k9s, lazydocker), keyboard driven.
- Shape 2: menu driven (raspi-config), lowest learning curve.
- Shape 3 (recommended): the same screens as the web face, rendered by
  Textual, with Shape 1 shortcuts layered on.

## Installer flow

0. Bootstrap: existing one-liner runs `sb setup` unchanged; also installs the
   UI package and daemon; on a fork repoints the git remote.
1. Preflight: Ubuntu release, amd64, not LXC, no desktop, nothing
   preinstalled, ports 80/443 reachable, disk, root or sudo.
2. Account and domain: accounts.yml, schema password rule, domain DNS check
   and Cloudflare TLD blocklist.
3. DNS and certificates: Cloudflare token, other provider (providers.yml and
   `traefik.provider`), or manual wildcard record with a wait-until-resolves.
4. Storage: local only, import existing rclone.conf, or the rclone wizard.
   Writes the remotes list.
5. Install type and apps: saltbox, mediabox, feederbox or custom. App picker
   by category. Writes `media_servers_enabled`, `download_clients_enabled`,
   `download_indexers_enabled`, `saltbox_roles`, `sandbox_roles`.
6. Advanced (collapsed): timezone, IPv6, proxied DNS, GPU, HSTS, backup
   destination, Hetzner VLAN.
7. Review: diff of every file and the commands; `sb validate-config`.
8. Run: `sb install preinstall`, reboot-and-continue via a plan file the
   daemon finishes on boot, then `sb install <type>`, then the UI role.
9. Done: URLs, logins, API keys from the MOTD config and facts.

## Rclone wizard

- Use `rclone config create NAME TYPE --non-interactive --continue --state`
  so the UI renders rclone's own questions for any backend.
- OAuth on a headless server: show the exact `rclone authorize` command for
  the user's laptop and a paste box for the token. Google service accounts:
  upload JSON files to `/opt/sa`.
- Verify with `rclone lsd`, highlight the expected Media layout, offer to
  create Media/Movies, TV, Music.
- Saltbox settings in the same screen: template, union, upload, VFS cache.
  Then `sb install mounts`.

## Day-two scope (everything in scope)

Apps (catalog, install, redeploy, remove, reset tags, instances, generated
settings forms, raw inventory editor with diff, setup checklists, container
logs and stats, update available), Storage (remotes, mounts, Cloudplow, disk
usage breakdown, local and NAS setups, feeder mount, crypt), System (update
with announcements and migrations, reboot indicator, NVIDIA, timezone,
locale, shell, MOTD, Tailscale, Themepark, Crowdsec, Gluetun), Backup and
Restore (run in background, schedule, retention, restore wizard, migration
guides), Jobs (any tag with skip-tags and extra vars, live output, history),
Support (diag, sanitized support bundle, config validation, docs links).

## Stack

- Option 1 (recommended): Python 3.12 engine, daemon and TUI (Textual,
  FastAPI) in their own venv; React web face in TypeScript built in CI and
  served as static files; role-defaults parser ported to Python with real
  roles as fixtures.
- Option 2: Python everything with HTMX. One language, clunkier web.
- Option 3: Go inside a fork of sb-go. Only upstream-plausible option; two
  forks, slowest iteration.

## Fork or upstream

- Fork: full control, ship in weeks, Python fine. Costs: own compatibility
  with an aggressively refactoring upstream, own bootstrap and remote, every
  UI user is a fork user.
- Upstream: survives refactors, delivered by `sb update`, community testing.
  Costs: realistic rejection (stated no-GUI position, Go only, rules against
  AI-written roles), months of review.
- Middle path (recommended regardless): sidecar. Keep the Saltbox repo stock,
  put the UI in its own directory and package installed by one new role, and
  consume Saltbox only through `sb`, schemas, role defaults and facts. The
  fork then carries one commit's worth of difference.

## Phases

0. Engine foundation, no UI (1 week): config service, schema validators,
   role-defaults parser with fixtures, catalog, runner, state, JSON CLI, unit
   tests, CI job. **Done.**
1. TUI installer (2 weeks): the wizard incl. rclone and reboot-and-continue.
   **Built** (`ui/saltbox_ui/installer`, `ui/saltbox_ui/rclone`,
   `ui/saltbox_ui/tui`): eleven steps, preflight, plan persisted after every
   step, rclone remotes through `rclone config create --non-interactive`
   with the headless `rclone authorize` flow, resume after the preinstall
   reboot, `--serve` for a browser. Covered by pilot tests against a fake
   `sb` and `rclone`. **Still to do:** a run on a throwaway Ubuntu 24.04 VM
   against the real `sb`, and the install-time packaging (pipx/uv tool line
   in the fork's bootstrap).
2. Daemon and web face (2 weeks): systemd, socket API, WebSocket jobs,
   Traefik file-provider route behind Authelia, React Overview/Apps/Jobs/
   Settings. **Built** (`ui/saltbox_ui/daemon`, `ui/web`): FastAPI over the
   engine, bearer token injected by the Traefik route after Authelia, jobs
   in a background thread with a WebSocket log stream and cancel, React
   pages for overview (needs-attention list), apps (tiles plus installed
   table, per-app overrides editor and role defaults), jobs (run, history,
   live log) and config (editor with schema validation, inventory). The
   installer's done screen enables it. The TUI still uses the engine
   directly; sharing the runner lock keeps the two from colliding, so the
   switch to the API is deferred. **Still to do:** the VM run, and
   packaging the web build so the server does not need node.
3. Day-two depth (2 weeks): Storage, Backup and Restore, Support, setup
   checklists for the Saltbox selection, instances, Sandbox catalog.
4. Ongoing: upstream merge routine, docs, release process, security review.

## Decisions needed

1. Web style: D hybrid, or a different mix.
2. TUI shape: Shape 3 with Shape 1 shortcuts, or something else.
3. Stack: Option 1 unless upstream is the real goal (then Option 3).
4. Fork posture: sidecar layout; confirm owning a fork bootstrap one-liner.
5. Name: command and subdomain. Working names `saltbox-ui` and
   `saltbox.<domain>`.
