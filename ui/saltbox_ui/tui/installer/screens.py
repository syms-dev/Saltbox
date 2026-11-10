"""The installer wizard steps."""

from __future__ import annotations

import threading
import time
from typing import Any

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Checkbox,
    Collapsible,
    Input,
    Log,
    RadioButton,
    RadioSet,
    Select,
    SelectionList,
    Static,
)

from ...catalog.catalog import is_listed_app
from ...installer.plan import DNS_MODES, PROFILES, PROVIDER_FIELDS, Remote
from ...installer.preflight import run_preflight, summarize
from ...plex import Pin, PlexError
from ...rclone import RcloneError
from ...schema import validators as v
from ...schema.api_checks import check_cloudflare
from ..widgets import CheckRow, FieldRow, FilterableSelection, StepScreen
from .rclone_screen import RcloneQuestionScreen

MEDIA_SERVERS = [("Plex", "plex"), ("Emby", "emby"), ("Jellyfin", "jellyfin")]
DOWNLOAD_CLIENTS = [
    ("qBittorrent (torrents)", "qbittorrent"),
    ("SABnzbd (usenet)", "sabnzbd"),
    ("NZBGet (usenet)", "nzbget"),
    ("Deluge (torrents)", "deluge"),
]
INDEXERS = [("Jackett", "jackett"), ("NZBHydra2", "nzbhydra2"), ("Prowlarr", "prowlarr")]
PROFILE_ROLE_LISTS = {
    "saltbox": "saltbox_roles",
    "mediabox": "mediabox_roles",
    "feederbox": "feederbox_roles",
}
# Entries in the profile lists that stand for the pickers below, not single apps.
SELECTOR_GROUPS = {"media_server", "download_clients", "download_indexers"}
SELECTOR_ROLES = {
    "plex",
    "emby",
    "jellyfin",
    "qbittorrent",
    "sabnzbd",
    "nzbget",
    "deluge",
    "jackett",
    "nzbhydra2",
    "prowlarr",
}


def extra_app_choices(apps: list) -> list:
    """Saltbox apps worth offering as extras, sorted by title.

    Entries without a docs category are maintenance tags (Plex Db, Arr Db,
    Cloudplow Disable) rather than apps, so they are left out too.
    """
    chosen = [
        a for a in apps if a.repo == "saltbox" and a.role not in SELECTOR_ROLES and is_listed_app(a)
    ]
    return sorted(chosen, key=lambda a: a.title.lower())


def extra_app_label(app) -> str:
    label = app.title
    if app.summary:
        label += f"  ·  {app.summary[:60]}"
    return label


def _session(screen: StepScreen):
    return screen.app.session  # type: ignore[attr-defined]


def _plan(screen: StepScreen):
    return screen.app.session.plan  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
class WelcomeScreen(StepScreen):
    TITLE = "Welcome"
    SHOW_BACK = False
    NEXT_LABEL = "Start"

    def body(self) -> ComposeResult:
        session = _session(self)
        yield Static("This wizard installs Saltbox on this server.", classes="lede")
        yield Static(
            "It writes the same accounts.yml, settings.yml and adv_settings.yml the docs "
            "describe, runs sb install preinstall, helps with rclone remotes, then runs the "
            "install you pick. You can stop at any time; progress is saved."
        )
        yield Static("")
        yield Static(f"Saltbox repo: {session.layout.repo}", classes="hint")
        yield Static(f"sb binary:    {session.layout.sb_binary}", classes="hint")
        if session.resumable:
            yield Static("")
            yield Static(
                f"An unfinished install was found (phase: {session.plan.phase}).",
                classes="warn",
            )
            with Horizontal():
                yield Button("Resume where it stopped", id="resume", variant="success")
                yield Button("Start over", id="discard")

    @on(Button.Pressed, "#resume")
    def _resume(self) -> None:
        self.app.resume()  # type: ignore[attr-defined]

    @on(Button.Pressed, "#discard")
    def _discard(self) -> None:
        _session(self).discard()
        self.app.notify("Previous plan discarded")
        self.query_one("#resume", Button).disabled = True
        self.query_one("#discard", Button).disabled = True


# ---------------------------------------------------------------------------
class PreflightScreen(StepScreen):
    TITLE = "Preflight checks"

    def body(self) -> ComposeResult:
        yield Static("Checking this server against Saltbox's requirements.", classes="lede")
        yield Vertical(id="check-list")
        yield Static("", id="preflight-summary")
        yield Button("Run again", id="rerun")

    def on_mount(self) -> None:
        self.set_next_enabled(False)
        self.run_checks()

    @on(Button.Pressed, "#rerun")
    def _rerun(self) -> None:
        self.run_checks()

    @work(thread=True, exclusive=True)
    def run_checks(self) -> None:
        app = self.app
        session = _session(self)
        probe = app.probe_factory(session.layout)  # type: ignore[attr-defined]
        checks = run_preflight(session.layout, probe)
        app.call_from_thread(self.render_checks, checks)

    def render_checks(self, checks) -> None:
        container = self.query_one("#check-list", Vertical)
        container.remove_children()
        container.mount_all(
            CheckRow(check.id, check.title, check.status, check.detail, check.hint)
            for check in checks
        )
        counts = summarize(checks)
        blocked = counts["fail"] > 0
        summary = self.query_one("#preflight-summary", Static)
        text = f"{counts['pass']} passed, {counts['warn']} warnings, {counts['fail']} failed."
        if blocked:
            text += " Fix the failed checks and run again."
        elif counts["warn"]:
            text += " Warnings do not block the install, but read them."
        summary.update(text)
        summary.set_classes("error" if blocked else "ok")
        self.set_next_enabled(not blocked)


# ---------------------------------------------------------------------------
class AccountScreen(StepScreen):
    TITLE = "Account and domain"

    def body(self) -> ComposeResult:
        plan = _plan(self)
        yield Static(
            "The user runs everything. It is created if missing. Never use root.",
            classes="lede",
        )
        yield FieldRow("Username", Input(plan.user_name, id="user_name"))
        yield FieldRow(
            "Password",
            Input(plan.user_pass, password=True, id="user_pass"),
            "12 characters or more. Also used as the first login for several apps.",
        )
        yield FieldRow("Confirm password", Input(plan.user_pass, password=True, id="user_pass2"))
        yield FieldRow(
            "Domain",
            Input(plan.domain, id="domain", placeholder="example.com"),
            "Apps are reached at app.domain. Enter the part below the app names.",
        )
        yield FieldRow(
            "Email",
            Input(plan.email, id="email", placeholder="you@example.com"),
            "Used for Let's Encrypt certificates.",
        )
        yield FieldRow(
            "SSH public key (optional)",
            Input(
                plan.ssh_key,
                id="ssh_key",
                placeholder="ssh-ed25519 AAAA… or https://github.com/you.keys",
            ),
            "Added to the user's authorized_keys. A GitHub .keys URL works too.",
        )

    def _value(self, widget_id: str) -> str:
        return self.query_one(f"#{widget_id}", Input).value.strip()

    def commit(self) -> str | None:
        plan = _plan(self)
        name = self._value("user_name")
        if not name or name == "root":
            return "Pick a username other than root"
        password = self.query_one("#user_pass", Input).value
        if len(password) < 12:
            return "The password must be at least 12 characters"
        if password != self.query_one("#user_pass2", Input).value:
            return "The passwords do not match"
        domain = self._value("domain").lower()
        try:
            v.validate_hostname_strict(domain, {})
        except ValueError as error:
            return f"Domain: {error}"
        if domain == "testsaltbox.ml":
            return "Enter your own domain"
        email = self._value("email")
        if not v.is_valid_email(email) or email == "your@email.com":
            return "Enter a valid email address"
        ssh_key = self._value("ssh_key")
        if ssh_key and not v.is_ssh_key_or_url(ssh_key):
            return "The SSH key must be a public key line or a URL"
        plan.user_name, plan.user_pass, plan.domain = name, password, domain
        plan.email, plan.ssh_key = email, ssh_key
        _session(self).save()
        return None


# ---------------------------------------------------------------------------
class DnsScreen(StepScreen):
    TITLE = "DNS and certificates"

    MODE_LABELS = [
        ("cloudflare_token", "Cloudflare, scoped API token (recommended)"),
        ("cloudflare_global", "Cloudflare, Global API key and email"),
        ("provider", "Another DNS provider Traefik can use for certificates"),
        ("manual", "I manage DNS myself (wildcard A record, HTTP certificate validation)"),
    ]

    def body(self) -> ComposeResult:
        plan = _plan(self)
        yield Static(
            "With Cloudflare, Saltbox creates every app's DNS record for you.", classes="lede"
        )
        with RadioSet(id="dns_mode"):
            for mode, label in self.MODE_LABELS:
                yield RadioButton(label, value=(plan.dns_mode == mode), name=mode)
        with Vertical(id="cf_token_box"):
            yield FieldRow(
                "Scoped token",
                Input(plan.cloudflare_token, password=True, id="cf_token"),
                "Zone Read, DNS Edit, Zone Settings Read, Cache Purge, Config Settings Edit.",
            )
        with Vertical(id="cf_global_box"):
            yield FieldRow("Global API key", Input(plan.cloudflare_api, password=True, id="cf_api"))
            yield FieldRow("Cloudflare account email", Input(plan.cloudflare_email, id="cf_email"))
        with Vertical(id="provider_box"):
            yield FieldRow(
                "Provider",
                Select(
                    [(name, name) for name in PROVIDER_FIELDS],
                    value=plan.provider or Select.NULL,
                    id="provider",
                ),
            )
            yield Vertical(id="provider_fields")
        with Vertical(id="manual_box"):
            yield Static(
                "Create a wildcard A record (*) pointing at this server's public IP before "
                "continuing. Certificates will use HTTP validation on port 80.",
                classes="hint",
            )
        yield Static("Options", classes="section")
        yield Checkbox(
            "Proxy records through Cloudflare (orange cloud)", plan.dns_proxied, id="proxied"
        )
        yield Checkbox("Manage IPv6 (AAAA) records and Docker IPv6", plan.dns_ipv6, id="ipv6")
        yield Checkbox("Use ZeroSSL instead of Let's Encrypt", plan.zerossl, id="zerossl")
        with Horizontal():
            yield Button("Test Cloudflare credentials", id="test_cf")
            yield Static("", id="test_result")

    def on_mount(self) -> None:
        self._render_provider_fields(_plan(self).provider)
        self._toggle_boxes(_plan(self).dns_mode)

    def _toggle_boxes(self, mode: str) -> None:
        self.query_one("#cf_token_box").display = mode == "cloudflare_token"
        self.query_one("#cf_global_box").display = mode == "cloudflare_global"
        self.query_one("#provider_box").display = mode == "provider"
        self.query_one("#manual_box").display = mode == "manual"
        self.query_one("#test_cf", Button).display = mode.startswith("cloudflare")

    @on(RadioSet.Changed, "#dns_mode")
    def _mode_changed(self, event: RadioSet.Changed) -> None:
        self._toggle_boxes(event.pressed.name or "cloudflare_token")

    @on(Select.Changed, "#provider")
    def _provider_changed(self, event: Select.Changed) -> None:
        self._render_provider_fields(event.value if isinstance(event.value, str) else "")

    def _render_provider_fields(self, provider: str) -> None:
        box = self.query_one("#provider_fields", Vertical)
        box.remove_children()
        plan = _plan(self)
        for key in PROVIDER_FIELDS.get(provider, []):
            secret = any(s in key for s in ("key", "secret", "token", "password"))
            current = plan.provider_credentials.get(key, "") if plan.provider == provider else ""
            box.mount(FieldRow(key, Input(current, password=secret, id=f"prov_{key}")))

    def _mode(self) -> str:
        pressed = self.query_one("#dns_mode", RadioSet).pressed_button
        return (pressed.name if pressed else None) or "cloudflare_token"

    @on(Button.Pressed, "#test_cf")
    def _test(self) -> None:
        error = self.commit()
        if error:
            self.notify_error(error)
            return
        self.query_one("#test_result", Static).update("testing…")
        self.test_cloudflare()

    @work(thread=True, exclusive=True)
    def test_cloudflare(self) -> None:
        plan = _plan(self)
        value = {
            "api": plan.cloudflare_api,
            "email": plan.cloudflare_email,
            "scoped_token": plan.cloudflare_token,
        }
        try:
            check_cloudflare(value, {"user": {"domain": plan.domain}})
            result, ok = "Cloudflare credentials and zone verified", True
        except Exception as error:
            result, ok = str(error), False
        self.app.call_from_thread(self._show_test, result, ok)

    def _show_test(self, text: str, ok: bool) -> None:
        widget = self.query_one("#test_result", Static)
        widget.update(text)
        widget.set_classes("ok" if ok else "error")

    def commit(self) -> str | None:
        plan = _plan(self)
        mode = self._mode()
        if mode not in DNS_MODES:
            return "Pick a DNS mode"
        plan.dns_mode = mode
        plan.cloudflare_token = plan.cloudflare_api = plan.cloudflare_email = ""
        if mode == "cloudflare_token":
            plan.cloudflare_token = self.query_one("#cf_token", Input).value.strip()
            if not plan.cloudflare_token:
                return "Enter the Cloudflare scoped token"
        elif mode == "cloudflare_global":
            plan.cloudflare_api = self.query_one("#cf_api", Input).value.strip()
            plan.cloudflare_email = self.query_one("#cf_email", Input).value.strip()
            if not plan.cloudflare_api or not v.is_valid_email(plan.cloudflare_email):
                return "Enter the Global API key and the account email"
        elif mode == "provider":
            provider = self.query_one("#provider", Select).value
            if not isinstance(provider, str) or provider not in PROVIDER_FIELDS:
                return "Pick a DNS provider"
            plan.provider = provider
            plan.provider_credentials = {
                key: self.query_one(f"#prov_{key}", Input).value.strip()
                for key in PROVIDER_FIELDS[provider]
            }
            if not any(plan.provider_credentials.values()):
                return f"Enter the {provider} credentials"
        plan.dns_proxied = self.query_one("#proxied", Checkbox).value
        plan.dns_ipv6 = self.query_one("#ipv6", Checkbox).value
        if plan.dns_ipv6 and not self.app.ipv6_check():  # type: ignore[attr-defined]
            plan.dns_ipv6 = False
            return (
                "This server has no working IPv6 internet connection, so Saltbox can't create "
                "IPv6 records and the install would fail. Untick the IPv6 option."
            )
        plan.zerossl = self.query_one("#zerossl", Checkbox).value
        _session(self).save()
        return None


# ---------------------------------------------------------------------------
class AppsScreen(StepScreen):
    TITLE = "Install type and apps"

    PROFILE_LABELS = [
        ("saltbox", "Saltbox: all-in-one, downloading and playback"),
        ("mediabox", "Mediabox: playback only (media server, requests, scanner)"),
        ("feederbox", "Feederbox: downloading only (clients, indexers, *arr)"),
        ("core", "Core only: Docker, Traefik, Authelia, mounts; add apps later"),
        ("custom", "Custom: core plus exactly the apps I pick below"),
    ]

    def body(self) -> ComposeResult:
        plan = _plan(self)
        session = _session(self)
        yield Static("Pick an install type, then adjust the apps.", classes="lede")
        with RadioSet(id="profile"):
            for key, label in self.PROFILE_LABELS:
                yield RadioButton(label, value=(plan.profile == key), name=key)
        yield Static("", id="profile_includes", classes="hint")
        yield Static("Media server", classes="section")
        yield SelectionList[str](
            *[(label, value, value in plan.media_servers) for label, value in MEDIA_SERVERS],
            id="media_servers",
        )
        yield Static("Download clients", classes="section")
        yield SelectionList[str](
            *[(label, value, value in plan.download_clients) for label, value in DOWNLOAD_CLIENTS],
            id="download_clients",
        )
        yield Static("Indexers", classes="section")
        yield SelectionList[str](
            *[(label, value, value in plan.download_indexers) for label, value in INDEXERS],
            id="download_indexers",
        )
        self._extra_apps = extra_app_choices(session.catalog.apps())
        shown = self._extras_for(plan.profile)
        with Collapsible(title=self._extras_title(shown), collapsed=True, id="extras_box"):
            yield FilterableSelection(
                [(extra_app_label(a), a.sb_tag or a.role) for a in shown],
                plan.extra_apps,
                id="extra_apps",
                placeholder="Filter apps…",
            )
        sandbox = [
            (f"{m.get('title', role)}  ·  {m.get('summary', '')[:60]}", role)
            for key, m in sorted(session.catalog.metadata.items())
            if key.startswith("sandbox/")
            for role in [key.split("/", 1)[1]]
        ]
        with Collapsible(
            title=f"Sandbox apps, community maintained ({len(sandbox)})", collapsed=True
        ):
            yield FilterableSelection(
                sandbox, plan.sandbox_apps, id="sandbox_apps", placeholder="Filter…"
            )
        yield Static("Authelia single sign-on", classes="section")
        yield Checkbox(
            "Run Authelia on this server (the login page in front of every app)",
            plan.authelia_master,
            id="authelia_master",
        )
        yield Static(
            "Keep this ticked. Untick it only when another Saltbox server already runs "
            "Authelia and this one should use that.",
            classes="hint",
        )
        yield FieldRow(
            "Authelia subdomain", Input(plan.authelia_subdomain, id="authelia_subdomain")
        )

    def included(self, profile: str) -> list[str]:
        """Apps the install type already installs, besides the pickers below."""
        var = PROFILE_ROLE_LISTS.get(profile)
        roles = _session(self).catalog.profiles.get(var, []) if var else []
        return [role for role in roles if role not in SELECTOR_GROUPS]

    def _show_included(self, profile: str) -> None:
        roles = self.included(profile)
        if roles:
            text = (
                f"Already included: {', '.join(roles)}. Pick the media server, download "
                "clients and indexers below; add anything else under More Saltbox apps."
            )
        else:
            text = (
                "Installs Docker, Traefik, Authelia and the mounts, plus only the apps you "
                "pick below."
            )
        self.query_one("#profile_includes", Static).update(text)
        shown = self._extras_for(profile)
        self.query_one("#extra_apps", FilterableSelection).set_items(
            [(extra_app_label(a), a.sb_tag or a.role) for a in shown]
        )
        self.query_one("#extras_box", Collapsible).title = self._extras_title(shown)

    def _extras_for(self, profile: str) -> list:
        """Extras not already installed by ``profile``."""
        included = set(self.included(profile))
        return [a for a in self._extra_apps if a.role not in included]

    @staticmethod
    def _extras_title(shown: list) -> str:
        return f"More Saltbox apps, on top of the install type ({len(shown)})"

    def on_mount(self) -> None:
        self._show_included(_plan(self).profile)

    @on(RadioSet.Changed, "#profile")
    def _profile_changed(self, event: RadioSet.Changed) -> None:
        self._show_included(event.pressed.name or "saltbox")

    def commit(self) -> str | None:
        plan = _plan(self)
        pressed = self.query_one("#profile", RadioSet).pressed_button
        profile = (pressed.name if pressed else None) or "saltbox"
        if profile not in PROFILES:
            return "Pick an install type"
        plan.profile = profile
        plan.media_servers = list(self.query_one("#media_servers", SelectionList).selected)
        plan.download_clients = list(self.query_one("#download_clients", SelectionList).selected)
        plan.download_indexers = list(self.query_one("#download_indexers", SelectionList).selected)
        if profile in {"saltbox", "mediabox"} and not plan.media_servers:
            return "Pick at least one media server, or choose a different install type"
        already = set(self.included(profile))
        plan.extra_apps = [
            app
            for app in self.query_one("#extra_apps", FilterableSelection).selected
            if app not in already
        ]
        plan.sandbox_apps = self.query_one("#sandbox_apps", FilterableSelection).selected
        if profile == "custom":
            selected = plan.media_servers + plan.download_clients + plan.download_indexers
            plan.extra_apps = [a for a in selected if a not in plan.extra_apps] + plan.extra_apps
        if plan.installs_jellyfin:
            return (
                "Jellyfin stops mid-install for its browser setup wizard, which this installer "
                "can't wait for yet. Untick it here and run 'sudo sb install jellyfin' in a "
                "terminal after the install."
            )
        plan.authelia_master = self.query_one("#authelia_master", Checkbox).value
        subdomain = self.query_one("#authelia_subdomain", Input).value.strip()
        try:
            v.validate_subdomain(subdomain, {})
        except ValueError as error:
            return f"Authelia subdomain: {error}"
        plan.authelia_subdomain = subdomain
        _session(self).save()
        return None


# ---------------------------------------------------------------------------
class AdvancedScreen(StepScreen):
    TITLE = "Advanced"

    def body(self) -> ComposeResult:
        plan = _plan(self)
        yield Static("Defaults are fine for most servers.", classes="lede")
        yield FieldRow(
            "Timezone",
            Input(plan.timezone, id="timezone"),
            "auto picks it from the server's location, or a TZ name such as Europe/Copenhagen",
        )
        yield FieldRow(
            "Shell",
            Select(
                [("bash", "bash"), ("zsh", "zsh")], value=plan.shell, allow_blank=False, id="shell"
            ),
        )
        yield Checkbox("Set up Intel GPU transcoding", plan.intel_gpu, id="intel_gpu")
        yield Checkbox("Enable HSTS", plan.hsts, id="hsts")
        yield FieldRow("Downloads folder", Input(plan.downloads, id="downloads"))
        yield FieldRow(
            "Transcodes folder",
            Input(plan.transcodes, id="transcodes"),
            "Not /tmp: it is cleared on reboot and Plex then fails to start transcodes",
        )
        yield Static("Docker Hub (optional, doubles the image pull limit)", classes="section")
        yield FieldRow("Docker Hub user", Input(plan.dockerhub_user, id="dh_user"))
        yield FieldRow(
            "Docker Hub access token", Input(plan.dockerhub_token, password=True, id="dh_token")
        )
        yield Static("Backups", classes="section")
        yield Checkbox("Keep a local copy of backups", plan.backup_local, id="backup_local")
        yield FieldRow(
            "Schedule",
            Select(
                [(c, c) for c in ("weekly", "daily", "monthly")],
                value=plan.backup_cron,
                allow_blank=False,
                id="backup_cron",
            ),
            "Nothing is scheduled until you run set-backup after the install.",
        )

    def commit(self) -> str | None:
        plan = _plan(self)
        timezone = self.query_one("#timezone", Input).value.strip() or "auto"
        try:
            v.validate_timezone(timezone, {})
        except ValueError as error:
            return str(error)
        plan.timezone = timezone
        plan.shell = str(self.query_one("#shell", Select).value)
        plan.intel_gpu = self.query_one("#intel_gpu", Checkbox).value
        plan.hsts = self.query_one("#hsts", Checkbox).value
        downloads = self.query_one("#downloads", Input).value.strip()
        transcodes = self.query_one("#transcodes", Input).value.strip()
        if not downloads.startswith("/") or not transcodes.startswith("/"):
            return "Folders must be absolute paths"
        plan.downloads, plan.transcodes = downloads, transcodes
        plan.dockerhub_user = self.query_one("#dh_user", Input).value.strip()
        plan.dockerhub_token = self.query_one("#dh_token", Input).value.strip()
        if bool(plan.dockerhub_user) != bool(plan.dockerhub_token):
            return "Enter both the Docker Hub user and token, or neither"
        plan.backup_local = self.query_one("#backup_local", Checkbox).value
        plan.backup_cron = str(self.query_one("#backup_cron", Select).value)
        _session(self).save()
        return None


# ---------------------------------------------------------------------------
class ReviewScreen(StepScreen):
    TITLE = "Review"
    NEXT_LABEL = "Write config and continue"

    def body(self) -> ComposeResult:
        plan = _plan(self)
        yield Static(
            "These files will be written, then validated the way sb validate-config does.",
            classes="lede",
        )
        with Vertical(id="summary"):
            for label, value in plan.summary():
                yield Static(f"{label:<18} {value}")
        yield Static(
            "Files: accounts.yml, settings.yml, adv_settings.yml, backup_config.yml"
            + (", providers.yml" if plan.dns_mode == "provider" else "")
            + ", inventories/host_vars/localhost.yml",
            classes="hint",
        )
        yield Static("Then: sb install preinstall", classes="hint")
        yield Static("", id="issues")

    def commit(self) -> str | None:
        session = _session(self)
        try:
            session.apply_config()
        except OSError as error:
            return f"Could not write configuration: {error}"
        results = session.validate()
        issues = self.query_one("#issues", Static)
        lines = [f"{name}: {i.message}" for name, found in results.items() for i in found]
        issues.update("\n".join(lines))
        if session.has_errors(results):
            return "Validation failed; see the list below"
        session.save()
        return None


# ---------------------------------------------------------------------------
class RunScreen(StepScreen):
    """Shared shape for the two screens that run sb."""

    SHOW_BACK = False
    INTRO = ""
    COMMAND = ""

    def body(self) -> ComposeResult:
        yield Static(self.INTRO, classes="lede")
        yield Static(f"$ {self.COMMAND}", classes="hint")
        yield Log(id="log")
        yield Static("", id="status")
        yield Button("Run", id="run", variant="success")

    def on_mount(self) -> None:
        self.set_next_enabled(False)

    def append(self, line: str) -> None:
        self.query_one("#log", Log).write_line(line)

    def set_status(self, text: str, ok: bool | None) -> None:
        widget = self.query_one("#status", Static)
        widget.update(text)
        widget.set_classes("ok" if ok else ("error" if ok is False else "hint"))

    @on(Button.Pressed, "#run")
    def _run(self) -> None:
        self.query_one("#run", Button).disabled = True
        self.set_status("running…", None)
        self.execute()

    @work(thread=True, exclusive=True)
    def execute(self) -> None:  # pragma: no cover - subclasses implement
        raise NotImplementedError

    def finished(self, job, success_text: str) -> None:
        if job.status == "succeeded":
            self.set_status(success_text, True)
            self.set_next_enabled(True)
        else:
            self.set_status(
                f"{job.kind} failed with exit code {job.returncode}; scroll up for the error", False
            )
            self.query_one("#run", Button).disabled = False
            self.query_one("#run", Button).label = "Run again"


class PreinstallScreen(RunScreen):
    TITLE = "Preinstall"
    INTRO = (
        "Creates the user, updates the kernel and GRUB, installs rclone. "
        "If the kernel is updated the server reboots itself; start the installer again "
        "afterwards and it continues from here."
    )
    COMMAND = "sb install preinstall"

    def on_mount(self) -> None:
        super().on_mount()
        session = _session(self)
        if session.plan.phase in {"storage", "install", "done"}:
            self.set_status("preinstall already completed", True)
            self.set_next_enabled(True)
            self.query_one("#run", Button).disabled = True

    @work(thread=True, exclusive=True)
    def execute(self) -> None:
        app = self.app
        session = _session(self)
        job = session.run_preinstall(on_line=lambda line: app.call_from_thread(self.append, line))
        app.call_from_thread(self.finished, job, "preinstall completed")


class InstallScreen(RunScreen):
    TITLE = "Install"
    INTRO = (
        "This takes a while. Each role prints its tasks; the recap at the end must say failed=0."
    )

    def body(self) -> ComposeResult:
        self.COMMAND = "sb install " + ",".join(_plan(self).install_tags())
        yield from super().body()

    @work(thread=True, exclusive=True)
    def execute(self) -> None:
        app = self.app
        session = _session(self)
        app.call_from_thread(self.append, "writing settings.yml with the storage choices")
        session.apply_config()
        job = session.run_install(on_line=lambda line: app.call_from_thread(self.append, line))
        app.call_from_thread(self.finished, job, "install completed")


# ---------------------------------------------------------------------------
class StorageScreen(StepScreen):
    TITLE = "Storage"

    def body(self) -> ComposeResult:
        plan = _plan(self)
        yield Static(
            "Where your media lives. Rclone remotes are created as the Saltbox user.",
            classes="lede",
        )
        with RadioSet(id="storage_mode"):
            yield RadioButton(
                "Local disk only. Media stays in /mnt/local; rclone disabled.",
                value=plan.storage_mode == "local",
                name="local",
            )
            yield RadioButton(
                "Use remotes already in rclone.conf",
                value=plan.storage_mode == "existing",
                name="existing",
            )
            yield RadioButton(
                "Create new rclone remotes now", value=plan.storage_mode == "create", name="create"
            )
        with Vertical(id="remote_box"):
            with Horizontal(id="create_row"):
                yield Input(placeholder="remote name, e.g. google", id="new_name")
                yield Select([], prompt="type", id="new_type")
                yield Button("Create", id="create")
            yield Button("Reload remotes", id="reload")
            yield Static("", id="remote_status", classes="hint")
            yield Vertical(id="remotes")
        yield Static(
            "Upload with Cloudplow moves finished media from /mnt/local/Media to the first remote "
            "marked for upload.",
            classes="hint",
        )

    def on_mount(self) -> None:
        self._toggle(_plan(self).storage_mode)
        self._render_remotes()
        if _plan(self).storage_mode != "local":
            self.load_remotes()

    def _toggle(self, mode: str) -> None:
        self.query_one("#remote_box").display = mode != "local"
        self.query_one("#create_row").display = mode == "create"

    @on(RadioSet.Changed, "#storage_mode")
    def _mode(self, event: RadioSet.Changed) -> None:
        mode = event.pressed.name or "local"
        self._toggle(mode)
        if mode != "local":
            self.load_remotes()

    @on(Button.Pressed, "#reload")
    def _reload(self) -> None:
        self.load_remotes()

    @work(thread=True, exclusive=True)
    def load_remotes(self) -> None:
        session = _session(self)
        service = session.rclone()
        try:
            types = service.remote_types()
            providers = [(p.name, p.name) for p in service.providers()]
        except RcloneError as error:
            self.app.call_from_thread(self._status, f"rclone: {error}")
            return
        self.app.call_from_thread(self._loaded, types, providers)

    def _status(self, text: str) -> None:
        self.query_one("#remote_status", Static).update(text)

    def _loaded(self, types: dict[str, str], providers: list[tuple[str, str]]) -> None:
        plan = _plan(self)
        known = {r.remote for r in plan.remotes}
        for name, kind in types.items():
            if name not in known:
                plan.remotes.append(Remote(name, template=_template_for(kind)))
        plan.remotes = [r for r in plan.remotes if r.remote in types]
        select = self.query_one("#new_type", Select)
        select.set_options(providers)
        self._status(
            f"{len(types)} remote(s) in rclone.conf" if types else "no remotes in rclone.conf yet"
        )
        self._render_remotes()

    def _render_remotes(self) -> None:
        box = self.query_one("#remotes", Vertical)
        box.remove_children()
        for index, remote in enumerate(_plan(self).remotes):
            box.mount(RemoteCard(index, remote))

    @on(Button.Pressed, "#create")
    def _create(self) -> None:
        name = self.query_one("#new_name", Input).value.strip()
        kind = self.query_one("#new_type", Select).value
        if not name or not isinstance(kind, str):
            self.notify_error("Enter a remote name and pick a type")
            return
        if name in {r.remote for r in _plan(self).remotes}:
            self.notify_error(f"A remote named {name} already exists")
            return
        service = _session(self).rclone()
        self.app.push_screen(RcloneQuestionScreen(service, name, kind), self._created)

    def _created(self, result: dict[str, Any] | None) -> None:
        if not result:
            return
        name = self.query_one("#new_name", Input).value.strip()
        plan = _plan(self)
        plan.remotes.append(
            Remote(name, template=_template_for(str(self.query_one("#new_type", Select).value)))
        )
        dirs = result.get("dirs") or []
        self._status(f"{name} created; top-level folders: {', '.join(dirs) if dirs else 'none'}")
        if "Media" not in dirs:
            self.app.notify(
                f"{name} has no Media folder yet; use the card's button to create "
                "Media/Movies, TV, Music",
                timeout=8,
            )
        self.query_one("#new_name", Input).value = ""
        _session(self).save()
        self._render_remotes()

    def commit(self) -> str | None:
        plan = _plan(self)
        pressed = self.query_one("#storage_mode", RadioSet).pressed_button
        mode = (pressed.name if pressed else None) or "local"
        plan.storage_mode = mode
        for card in self.query(RemoteCard):
            card.store()
        if mode == "local":
            plan.remotes = []
        elif not plan.remotes:
            return "No remotes configured. Create one, or choose local disk only."
        _session(self).save()
        return None


class RemoteCard(Vertical):
    def __init__(self, index: int, remote: Remote) -> None:
        super().__init__(classes="remote-card")
        self.index = index
        self.remote = remote

    def compose(self) -> ComposeResult:
        r = self.remote
        yield Static(f"[b]{r.remote}[/b]", markup=True)
        with Horizontal(classes="two-col"):
            yield Select(
                [(t, t) for t in ("google", "dropbox", "sftp", "nfs")],
                value=r.template,
                allow_blank=False,
                id=f"tpl_{self.index}",
            )
            yield Checkbox("in union (/mnt/unionfs)", r.union, id=f"union_{self.index}")
            yield Checkbox("upload here (Cloudplow)", r.upload, id=f"upload_{self.index}")
        with Horizontal(classes="two-col"):
            yield Checkbox("VFS cache", r.vfs_cache_enabled, id=f"vfs_{self.index}")
            yield Input(
                r.vfs_cache_size, placeholder="cache size, e.g. 50G", id=f"vfssize_{self.index}"
            )
            yield Button("Create Media folders", id=f"mkmedia_{self.index}")
            yield Button("Remove", id=f"remove_{self.index}")

    def store(self) -> None:
        r = self.remote
        r.template = str(self.query_one(f"#tpl_{self.index}", Select).value)
        r.union = self.query_one(f"#union_{self.index}", Checkbox).value
        r.upload = self.query_one(f"#upload_{self.index}", Checkbox).value
        r.vfs_cache_enabled = self.query_one(f"#vfs_{self.index}", Checkbox).value
        r.vfs_cache_size = self.query_one(f"#vfssize_{self.index}", Input).value.strip() or "50G"
        r.enable_refresh = r.template == "sftp"

    @on(Button.Pressed)
    def _buttons(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        screen = self.screen
        if button_id.startswith("remove_"):
            plan = screen.app.session.plan  # type: ignore[attr-defined]
            plan.remotes = [r for r in plan.remotes if r.remote != self.remote.remote]
            screen._render_remotes()  # type: ignore[attr-defined]
            event.stop()
        elif button_id.startswith("mkmedia_"):
            event.stop()
            self.make_media()

    @work(thread=True)
    def make_media(self) -> None:
        service = self.screen.app.session.rclone()  # type: ignore[attr-defined]
        try:
            created = service.ensure_media_layout(self.remote.remote)
            text = f"{self.remote.remote}: created {', '.join(created)}"
        except RcloneError as error:
            text = f"{self.remote.remote}: {error}"
        self.app.call_from_thread(self.app.notify, text, timeout=8)


def _template_for(remote_type: str) -> str:
    return {"drive": "google", "dropbox": "dropbox", "sftp": "sftp", "nfs": "nfs"}.get(
        remote_type, "google"
    )


# ---------------------------------------------------------------------------
class PlexScreen(StepScreen):
    """Link a Plex account so the Plex role finds a token and never stops to ask."""

    TITLE = "Plex account"
    NEXT_LABEL = "Continue to install"
    POLL_SECONDS = 2.0
    PIN_WAIT_SECONDS = 15 * 60  # plex.tv expires link codes after about 15 minutes

    def __init__(self, index: int, total: int, **kwargs: Any) -> None:
        super().__init__(index, total, **kwargs)
        self._cancel = threading.Event()

    def body(self) -> ComposeResult:
        plan = _plan(self)
        if not plan.installs_plex:
            yield Static("Plex isn't part of this install, so there's nothing to link.")
            return
        yield Static(
            "Saltbox claims your Plex server with your Plex account. Link it now, so the "
            "install doesn't stop halfway to ask.",
            classes="lede",
        )
        yield Static("", id="plex_status")
        yield Static("", id="plex_code", classes="code-box")
        with Horizontal():
            yield Button("Link Plex account", id="plex_link", variant="primary")
            yield Button("Cancel", id="plex_cancel")

    def on_mount(self) -> None:
        plan = _plan(self)
        if not plan.installs_plex:
            return
        self.query_one("#plex_code").display = False
        self.query_one("#plex_cancel").display = False
        if plan.plex_token:
            self._status(f"Linked to Plex as {plan.plex_username or 'your account'}.", True)
            self.query_one("#plex_link", Button).label = "Link a different account"
        else:
            self._status("Not linked yet.", None)
            self.set_next_enabled(False)

    def on_unmount(self) -> None:
        self._cancel.set()

    def _status(self, text: str, ok: bool | None) -> None:
        widget = self.query_one("#plex_status", Static)
        widget.update(text)
        widget.set_classes("ok" if ok else ("error" if ok is False else "hint"))

    @on(Button.Pressed, "#plex_link")
    def _link(self) -> None:
        self._cancel.set()
        self._cancel = threading.Event()
        self.query_one("#plex_link", Button).disabled = True
        self._status("Asking plex.tv for a link code…", None)
        self.link(self._cancel)

    @on(Button.Pressed, "#plex_cancel")
    def _cancel_link(self) -> None:
        self._cancel.set()
        self._reset("Cancelled. Press Link to get a new code.", None)

    @work(thread=True, exclusive=True)
    def link(self, cancel: threading.Event) -> None:
        session = _session(self)
        call = self.app.call_from_thread
        try:
            client = session.plex_client()
            pin = client.create_pin()
        except PlexError as error:
            call(self._reset, str(error), False)
            return
        call(self._show_pin, pin)
        deadline = time.monotonic() + self.PIN_WAIT_SECONDS
        while not cancel.is_set() and time.monotonic() < deadline:
            try:
                token = client.check_pin(pin)
                if token:
                    username = client.username(token)
                    session.save_plex_link(client.client_id, token, username)
                    call(self._linked, username)
                    return
            except PlexError as error:
                call(self._reset, str(error), False)
                return
            cancel.wait(self.POLL_SECONDS)
        if not cancel.is_set():
            call(self._reset, "The code expired. Press Link to get a new one.", False)

    def _show_pin(self, pin: Pin) -> None:
        code = self.query_one("#plex_code", Static)
        code.update(
            f"On any device, open {pin.link_url} and enter this code:\n\n"
            f"        {pin.code}\n\n"
            f"Or open this link instead:\n{pin.auth_url}"
        )
        code.display = True
        self.query_one("#plex_cancel").display = True
        self._status("Waiting for you to link the code…", None)

    def _linked(self, username: str) -> None:
        self.query_one("#plex_code").display = False
        self.query_one("#plex_cancel").display = False
        link = self.query_one("#plex_link", Button)
        link.disabled = False
        link.label = "Link a different account"
        self._status(f"Linked to Plex as {username or 'your account'}.", True)
        self.set_next_enabled(True)

    def _reset(self, text: str, ok: bool | None) -> None:
        self.query_one("#plex_code").display = False
        self.query_one("#plex_cancel").display = False
        self.query_one("#plex_link", Button).disabled = False
        self._status(text, ok)
        self.set_next_enabled(bool(_plan(self).plex_token))

    def commit(self) -> str | None:
        plan = _plan(self)
        if plan.installs_plex and not plan.plex_token:
            return "Link your Plex account first, or go back to Apps and untick Plex."
        return None


# ---------------------------------------------------------------------------
class DoneScreen(StepScreen):
    TITLE = "Done"
    SHOW_BACK = False
    NEXT_LABEL = "Exit"

    def body(self) -> ComposeResult:
        plan = _plan(self)
        session = _session(self)
        yield Static("Saltbox is installed. Reboot once, then set up the apps.", classes="lede")
        yield Static("Your apps", classes="section")
        for sub in sorted(
            set(
                plan.media_servers
                + plan.download_clients
                + plan.download_indexers
                + [a for a in plan.extra_apps if not a.startswith("sandbox-")]
            )
        ):
            yield Static(f"https://{sub}.{plan.domain}")
        yield Static(f"https://{plan.authelia_subdomain}.{plan.domain}   Authelia login")
        yield Static(f"https://dash.{plan.domain}   Traefik dashboard")
        yield Static("Logins", classes="section")
        yield Static(
            f"User: {plan.user_name}   Password: the one you entered. "
            "Several apps use it as their first login."
        )
        yield Static("Connect your apps", classes="section")
        yield Static(
            "Links Sonarr, Radarr and Lidarr to qBittorrent, Autoscan and Prowlarr and adds your "
            "Plex libraries. Run it any time with: sudo saltbox-ui --setup",
            classes="hint",
        )
        yield Button("Connect the apps", id="connect_apps", variant="primary")
        yield Static("Web UI", classes="section")
        yield Static(
            f"Manage this server from a browser at https://saltbox.{plan.domain}, behind "
            "Authelia. This writes a Traefik route and starts the saltbox-ui service.",
            classes="hint",
        )
        with Horizontal():
            yield Button("Enable the web UI", id="enable_web", variant="primary")
            yield Static("", id="web_status", classes="hint")
        yield Static("Next steps", classes="section")
        yield Static(
            "1. sudo reboot\n"
            f"2. Log in as {plan.user_name}, not root.\n"
            "3. Follow the app setup pages at https://docs.saltbox.dev/apps/\n"
            "4. Schedule backups: sb install set-backup\n"
            f"5. Config files: {session.layout.repo}"
        )
        if plan.notes:
            yield Static("Notes", classes="section")
            for note in plan.notes:
                yield Static(f"· {note}", classes="hint")

    @on(Button.Pressed, "#connect_apps")
    def _connect_apps(self) -> None:
        from ..setup_screen import SetupScreen

        factory = self.app.app_setup_factory  # type: ignore[attr-defined]
        self.app.push_screen(SetupScreen(factory(_session(self).layout)))

    @on(Button.Pressed, "#enable_web")
    def _enable_web(self) -> None:
        self.query_one("#enable_web", Button).disabled = True
        self.query_one("#web_status", Static).update("enabling…")
        self.enable_web()

    @work(thread=True, exclusive=True)
    def enable_web(self) -> None:
        session = _session(self)
        try:
            result = session.enable_web()
        except (OSError, ValueError) as error:
            self.app.call_from_thread(self._web_done, f"failed: {error}", False)
            return
        started = result.get("started", True)
        text = (
            f"ready at {result['url']}" if started else "unit written but the service did not start"
        )
        if result.get("warning"):
            text += f"; {result['warning']}"
        self.app.call_from_thread(self._web_done, text, started)

    def _web_done(self, text: str, ok: bool) -> None:
        status = self.query_one("#web_status", Static)
        status.update(text)
        status.set_classes("ok" if ok else "error")
        self.query_one("#enable_web", Button).disabled = ok
