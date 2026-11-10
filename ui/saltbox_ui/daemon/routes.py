"""HTTP and WebSocket routes.

Everything is a thin call into the engine. Writes go through the same
``ConfigService`` and ``Inventory`` the TUI and ``sbx`` use, so a file edited
in the browser keeps its comments and passes the same validation.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .. import __version__
from ..catalog.catalog import is_listed_app
from ..config.service import CONFIG_FILES
from ..runner import JobRunning
from ..secrets import (
    HIDDEN,
    Redactor,
    UnknownPlaceholder,
    mask_text,
    mask_tree,
    secret_values,
    tree_secrets,
    unmask_text,
)
from ..state import (
    cached_tags,
    disk_usage,
    list_containers,
    mounts,
    read_all_facts,
    read_motd_services,
    read_port_assignments,
    read_role_facts,
    reboot_required,
    redact_value,
    systemd_units,
)
from ..state.containers import CONTAINER_ACTIONS, container_action, container_logs
from ..state.system import backup_summary, container_stats, host_stats, tailscale_status
from ..yamlio import coerce_scalar, find_duplicate_keys, load_text, write_atomic

router = APIRouter()

STREAM_POLL_SECONDS = 0.25


def services(request: Request):
    return request.app.state.services


# -- meta and overview ---------------------------------------------------------
@router.get("/meta")
def meta(request: Request) -> dict[str, Any]:
    svc = services(request)
    return {
        "version": __version__,
        "layout": svc.layout.as_dict(),
        "saltbox": _git_describe(svc.layout.repo),
        "web": bool(svc.web_dir and (svc.web_dir / "index.html").exists()),
        "domain": _domain(svc),
        "user": _account(svc, "user.name"),
    }


def _account(svc, dotted: str) -> str | None:
    try:
        value = svc.config.get("accounts", dotted)
    except Exception:  # missing or unreadable accounts.yml
        return None
    return str(value) if value else None


def _domain(svc) -> str | None:
    """The box's domain from accounts.yml, for page titles; None until it is set."""
    try:
        value = svc.config.get("accounts", "user.domain")
    except Exception:  # missing or unreadable accounts.yml
        return None
    return str(value) if value and str(value) != "testsaltbox.ml" else None


@router.get("/overview")
def overview(request: Request) -> dict[str, Any]:
    svc = services(request)
    svc.updates.ensure_fresh()
    layout = svc.layout
    containers = _containers_or_none()
    issues = svc.config.validate_all()
    return {
        "host": {
            "disks": disk_usage(),
            "reboot_required": reboot_required(),
            "mounts": mounts(),
            "units": systemd_units(),
        },
        "install": {
            "installed": layout.facts_dir.exists() or (layout.appdata / "traefik").is_dir(),
            "configs_present": layout.config_file("accounts").exists(),
            "roles_with_facts": sorted(
                p.stem for p in layout.facts_dir.glob("*.ini") if layout.facts_dir.exists()
            ),
        },
        "containers": _container_summary(containers),
        "updates": _updates_summary(svc),
        "services": read_motd_services(layout),
        "jobs": {
            **_jobs_status(svc),
            "recent": [_job_view(svc, j) for j in svc.runner.jobs(limit=5)],
        },
        "config_issues": {
            name: [i.as_dict() for i in found] for name, found in issues.items() if found
        },
    }


# -- apps ------------------------------------------------------------------
@router.get("/apps")
def apps(request: Request, all: bool = False) -> list[dict[str, Any]]:
    svc = services(request)
    containers = _containers_or_none()
    by_name = {c["name"]: c for c in containers or []}
    updates = svc.updates.status_by_container()
    svc.updates.ensure_fresh()
    result = []
    for app in svc.catalog.apps(include_hidden=all):
        if not all and not is_listed_app(app):
            continue
        instances = svc.inventory.instances(app.role, app.default_instances or [app.role])
        data = app.as_dict()
        data["instances"] = instances
        # Most apps keep their config in <appdata>/<instance>; some (Autoheal, Watchtower)
        # keep none, so a container under the instance's name counts too.
        data["installed"] = any(
            (svc.layout.appdata / name).is_dir() or name in by_name for name in instances
        )
        data["containers"] = [
            _container_view(by_name[name], updates.get(name))
            for name in instances
            if name in by_name
        ]
        data["urls"] = [url for c in data["containers"] for url in c["urls"]]
        data["update_available"] = any(c["update"] == "update" for c in data["containers"])
        result.append(data)
    return sorted(result, key=lambda item: str(item["title"]).lower())


@router.get("/apps/{repo}/{role}")
def app_detail(request: Request, repo: str, role: str, reveal: bool = False) -> dict[str, Any]:
    svc = services(request)
    app = svc.catalog.app(role, repo)
    if app is None:
        raise HTTPException(404, f"unknown app {repo}/{role}")
    defaults = svc.catalog.defaults(role, repo)
    instances = svc.inventory.instances(role, app.default_instances or [role])
    containers = {c["name"]: c for c in _containers_or_none() or []}
    updates = svc.updates.status_by_container()
    views = [
        _container_view(containers[name], updates.get(name))
        for name in instances
        if name in containers
    ]
    overrides = svc.inventory.overrides_for(role, instances)
    return {
        "app": app.as_dict(),
        "containers": views,
        "urls": [url for view in views for url in view["urls"]],
        "update_available": any(view["update"] == "update" for view in views),
        "installed": bool(views) or any((svc.layout.appdata / n).is_dir() for n in instances),
        "instances": instances,
        "fields": [f.as_dict() for f in defaults.visible()] if defaults else [],
        "overrides": (overrides if reveal else mask_tree(overrides)),
        "facts": _facts_for(svc, role),
    }


class OverrideUpdate(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    unset: list[str] = Field(default_factory=list)


@router.put("/apps/{repo}/{role}/overrides")
def update_overrides(request: Request, repo: str, role: str, body: OverrideUpdate) -> dict:
    svc = services(request)
    if svc.catalog.app(role, repo) is None:
        raise HTTPException(404, f"unknown app {repo}/{role}")
    values = {key: _coerce(value) for key, value in body.values.items()}
    if values:
        svc.inventory.update(values)
    removed = [key for key in body.unset if svc.inventory.unset(key)]
    instances = svc.inventory.instances(role, [role])
    return {"overrides": svc.inventory.overrides_for(role, instances), "removed": removed}


@router.get("/catalog/categories")
def categories(request: Request) -> dict[str, list[str]]:
    return services(request).catalog.categories()


@router.get("/catalog/tags")
def tags(request: Request) -> dict[str, Any]:
    return cached_tags(services(request).layout)


# -- config ----------------------------------------------------------------
@router.get("/config")
def config_files(request: Request) -> list[dict[str, Any]]:
    svc = services(request)
    return [
        {
            "name": name,
            "filename": spec.filename,
            "exists": svc.config.exists(name),
            "source": svc.config.source(name),
            "optional": spec.optional,
            "schema": spec.schema is not None,
        }
        for name, spec in CONFIG_FILES.items()
    ]


@router.get("/config/{name}")
def config_file(request: Request, name: str, reveal: bool = False) -> dict[str, Any]:
    svc = services(request)
    if name not in CONFIG_FILES:
        raise HTTPException(404, f"unknown config file {name}")
    path = svc.config.path(name)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if not text:
        default = svc.config.default_path(name)
        text = default.read_text(encoding="utf-8") if default and default.exists() else ""
    data = svc.config.load_plain(name) if (path.exists() or text) else {}
    return {
        "name": name,
        "path": str(path),
        "source": svc.config.source(name),
        "text": text if reveal else mask_text(text),
        "data": data if reveal else mask_tree(data),
        "hidden": len(secret_values(text)),
        "issues": [i.as_dict() for i in svc.config.validate(name)],
    }


class ConfigText(BaseModel):
    text: str


@router.put("/config/{name}")
def write_config_file(request: Request, name: str, body: ConfigText) -> dict[str, Any]:
    svc = services(request)
    if name not in CONFIG_FILES:
        raise HTTPException(404, f"unknown config file {name}")
    path = svc.config.path(name)
    default = svc.config.default_path(name)
    text = _unmask(body.text, path if path.exists() or default is None else default)
    _check_yaml(text)
    write_atomic(path, text if text.endswith("\n") else text + "\n")
    svc.__dict__.pop("_redactor", None)
    return {"name": name, "issues": [i.as_dict() for i in svc.config.validate(name)]}


class ConfigValue(BaseModel):
    path: str
    value: Any


@router.patch("/config/{name}")
def set_config_value(request: Request, name: str, body: ConfigValue) -> dict[str, Any]:
    svc = services(request)
    if name not in CONFIG_FILES:
        raise HTTPException(404, f"unknown config file {name}")
    svc.config.set(name, body.path, _coerce(body.value))
    return {"name": name, "issues": [i.as_dict() for i in svc.config.validate(name)]}


@router.post("/config/validate")
def validate_config(request: Request, api: bool = False) -> dict[str, list[dict[str, str]]]:
    svc = services(request)
    results = svc.config.validate_all(api_checks=api)
    return {name: [i.as_dict() for i in found] for name, found in results.items()}


@router.get("/inventory")
def inventory(request: Request, reveal: bool = False) -> dict[str, Any]:
    svc = services(request)
    path = svc.layout.inventory
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    data = svc.inventory.as_dict()
    return {
        "path": str(path),
        "text": text if reveal else mask_text(text),
        "data": data if reveal else mask_tree(data),
        "hidden": len(secret_values(text)),
        "issues": [i.as_dict() for i in svc.config.validate_inventory()],
    }


@router.put("/inventory")
def write_inventory(request: Request, body: ConfigText) -> dict[str, Any]:
    svc = services(request)
    text = _unmask(body.text, svc.layout.inventory)
    _check_yaml(text)
    write_atomic(svc.layout.inventory, text if text.endswith("\n") else text + "\n")
    svc.__dict__.pop("_redactor", None)
    return {"issues": [i.as_dict() for i in svc.config.validate_inventory()]}


# -- state -----------------------------------------------------------------
@router.get("/state/facts")
def facts(request: Request, secrets: bool = False) -> dict[str, Any]:
    return read_all_facts(services(request).layout, redact=not secrets)


@router.get("/state/ports")
def ports(request: Request) -> dict[str, Any]:
    return read_port_assignments(services(request).layout)


@router.get("/state/containers")
def containers(request: Request) -> list[dict[str, Any]]:
    try:
        return list_containers()
    except Exception as error:
        raise HTTPException(503, f"docker unavailable: {error}") from error


@router.get("/state/motd")
def motd(request: Request, secrets: bool = False) -> list[dict[str, Any]]:
    return read_motd_services(services(request).layout, redact=not secrets)


@router.get("/state/host")
def host(request: Request) -> dict[str, Any]:
    return {
        "disks": disk_usage(),
        "mounts": mounts(),
        "units": systemd_units(),
        "reboot_required": reboot_required(),
    }


# -- updates -------------------------------------------------------------------
@router.get("/updates")
def updates_status(request: Request) -> dict[str, Any]:
    svc = services(request)
    svc.updates.ensure_fresh()
    return svc.updates.cached()


@router.post("/updates/check", status_code=202)
def updates_check(request: Request) -> dict[str, Any]:
    svc = services(request)
    started = svc.updates.refresh()
    return {"started": started, **svc.updates.cached()}


@router.post("/apps/{repo}/{role}/update", status_code=202)
def update_app(request: Request, repo: str, role: str) -> dict[str, Any]:
    svc = services(request)
    app = svc.catalog.app(role, repo)
    if app is None:
        raise HTTPException(404, f"unknown app {repo}/{role}")
    return _start_update(svc, [app])


@router.post("/updates/apply", status_code=202)
def update_all(request: Request) -> dict[str, Any]:
    svc = services(request)
    pending = {
        name
        for name, status in svc.updates.status_by_container().items()
        if status.get("status") == "update"
    }
    apps = [
        app
        for app in svc.catalog.apps()
        if pending & set(svc.inventory.instances(app.role, app.default_instances or [app.role]))
    ]
    if not apps:
        raise HTTPException(409, "nothing to update")
    return _start_update(svc, apps)


@router.post("/saltbox/update", status_code=202)
def update_saltbox(request: Request) -> dict[str, Any]:
    """Run ``sb update``: reset the checkouts to their branches and refresh settings."""
    svc = services(request)
    try:
        job = svc.jobs.start("update")
    except JobRunning as error:
        raise HTTPException(409, str(error)) from error
    return _job_view(svc, job)


def _start_update(svc, apps: list) -> dict[str, Any]:
    """Re-run each app's tag, which pulls its image and recreates its container.

    Containers routed through another container (qBittorrent inside Gluetun)
    cannot start against a recreated one, so their apps are re-run as well.
    """
    tags: list[str] = []
    names: set[str] = set()
    for app in apps:
        tag = app.sb_tag or app.install_tag or app.role
        if tag not in tags:
            tags.append(tag)
        names.update(svc.inventory.instances(app.role, app.default_instances or [app.role]))
    for container in _containers_or_none() or []:
        mode = str(container.get("network_mode", ""))
        if mode.startswith("container:") and mode.split(":", 1)[1] in names:
            dependent = _app_for_container(svc, container["name"])
            tag = dependent and (dependent.sb_tag or dependent.install_tag or dependent.role)
            if tag and tag not in tags:
                tags.append(tag)
    try:
        job = svc.jobs.start("install", tags=tags)
    except JobRunning as error:
        raise HTTPException(409, str(error)) from error
    return _job_view(svc, job)


def _app_for_container(svc, name: str):
    for app in svc.catalog.apps(include_hidden=True):
        if name in svc.inventory.instances(app.role, app.default_instances or [app.role]):
            return app
    return None


def _updates_summary(svc) -> dict[str, Any]:
    cached = svc.updates.cached()
    pending = sorted(
        {
            name
            for status in cached.get("images", {}).values()
            if status.get("status") == "update"
            for name in status.get("containers", [])
        }
    )
    return {
        "checked_at": cached.get("checked_at"),
        "running": cached["running"],
        "pending": pending,
        "saltbox": [
            repo["name"] for repo in cached.get("repos", []) if repo.get("status") == "update"
        ],
    }


def _container_view(container: dict[str, Any], update: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "name": container["name"],
        "status": container["status"],
        "health": container["health"],
        "urls": list(container.get("urls") or []),
        "image": container.get("image_ref") or container.get("image", ""),
        "update": (update or {}).get("status", "unknown"),
        "update_detail": (update or {}).get("detail", ""),
    }


# -- system -----------------------------------------------------------------------
RESOURCES_TTL_SECONDS = 5.0


@router.get("/resources")
def resources(request: Request) -> dict[str, Any]:
    """Host load and memory, and CPU and memory per container (refreshed every 5 s)."""
    svc = services(request)
    cached = svc.__dict__.get("_resources")
    if cached is not None and time.monotonic() - cached[0] < RESOURCES_TTL_SECONDS:
        return cached[1]
    data: dict[str, Any] = {"host": host_stats(), "containers": [], "error": ""}
    try:
        data["containers"] = container_stats()
    except RuntimeError as error:
        data["error"] = str(error)
    svc.__dict__["_resources"] = (time.monotonic(), data)
    return data


@router.get("/tailscale")
def tailscale(request: Request) -> dict[str, Any]:
    return tailscale_status()


@router.get("/backups")
def backups(request: Request) -> dict[str, Any]:
    svc = services(request)
    try:
        config = (
            svc.config.load_plain("backup_config") if svc.config.exists("backup_config") else {}
        )
        user = str(svc.config.get("accounts", "user.name") or "")
    except Exception:  # an unreadable file shows as "not configured"
        config, user = {}, ""
    summary = backup_summary(config, user)
    runs = [j for j in svc.runner.jobs(limit=200) if "backup" in j.tags or "backup2" in j.tags]
    summary["last_job"] = _job_view(svc, runs[0]) if runs else None
    return summary


@router.post("/backups/run", status_code=202)
def run_backup(request: Request) -> dict[str, Any]:
    """``sb install backup``: Saltbox stops the apps, archives /opt, starts them again."""
    svc = services(request)
    try:
        job = svc.jobs.start("install", tags=["backup"])
    except JobRunning as error:
        raise HTTPException(409, str(error)) from error
    return _job_view(svc, job)


# -- media ---------------------------------------------------------------------------
MEDIA_TTL_SECONDS = 15.0


@router.get("/media")
def media(request: Request) -> dict[str, Any]:
    """VPN, downloads, Plex sessions and the week ahead, each section on its own."""
    from ..appsetup.vpnport import docker_cat
    from ..media import media_snapshot

    svc = services(request)
    cached = svc.__dict__.get("_media")
    if cached is not None and time.monotonic() - cached[0] < MEDIA_TTL_SECONDS:
        return cached[1]
    setup = _app_setup(request)
    found = setup.discover()
    data = media_snapshot(
        found,
        _containers_or_none() or [],
        transport=getattr(setup, "transport", None),
        read_file=getattr(setup, "container_reader", None) or docker_cat,
        read_log=getattr(setup, "log_reader", None),
    )
    redact = _redactor(svc)
    for section in data.values():
        if isinstance(section, dict) and section.get("error"):
            section["error"] = redact(str(section["error"]))
    svc.__dict__["_media"] = (time.monotonic(), data)
    return data


# -- recyclarr ------------------------------------------------------------------------
class RecyclarrSelection(BaseModel):
    sonarr: list[str] = Field(default_factory=list)
    radarr: list[str] = Field(default_factory=list)


class RecyclarrSync(BaseModel):
    preview: bool = False


def _recyclarr_status(request: Request) -> dict[str, Any]:
    from .. import recyclarr

    svc = services(request)
    found = _app_setup(request).discover()
    containers = {c["name"]: c for c in _containers_or_none() or []}
    data = recyclarr.status(svc.layout, found, containers)
    runs = [j for j in svc.runner.jobs(limit=200) if j.kind == "recyclarr"]
    data["last_job"] = _job_view(svc, runs[0]) if runs else None
    return data


@router.get("/recyclarr")
def recyclarr_status(request: Request) -> dict[str, Any]:
    return _recyclarr_status(request)


@router.put("/recyclarr")
def recyclarr_save(request: Request, body: RecyclarrSelection) -> dict[str, Any]:
    """Write recyclarr.yml and secrets.yml for the chosen TRaSH profiles."""
    from .. import recyclarr

    svc = services(request)
    found = _app_setup(request).discover()
    try:
        result = recyclarr.write_config(svc.layout, found, body.model_dump())
    except recyclarr.RecyclarrError as error:
        raise HTTPException(400, str(error)) from error
    svc.__dict__.pop("_redactor", None)  # the new secrets.yml holds keys to hide
    return {**result, "status": _recyclarr_status(request)}


@router.post("/recyclarr/sync", status_code=202)
def recyclarr_sync(request: Request, body: RecyclarrSync) -> dict[str, Any]:
    """``recyclarr sync`` (or ``--preview``) in its container, with a live log."""
    svc = services(request)
    container = next((c for c in _containers_or_none() or [] if c["name"] == "recyclarr"), None)
    if container is None or container["status"] != "running":
        raise HTTPException(409, "the recyclarr container is not running")
    try:
        job = svc.jobs.start_recyclarr(preview=body.preview)
    except JobRunning as error:
        raise HTTPException(409, str(error)) from error
    return _job_view(svc, job)


# -- automation -------------------------------------------------------------------------
class AutomationSettings(BaseModel):
    alerts: dict[str, Any] = Field(default_factory=dict)
    maintenance: dict[str, Any] = Field(default_factory=dict)


def _automation_view(svc, settings: dict[str, Any], reveal: bool = False) -> dict[str, Any]:
    from .automation import EVENTS

    automation = svc.automation
    own = str(settings["alerts"].get("url") or "")
    view = json.loads(json.dumps(settings))
    if own and not reveal:
        view["alerts"]["url"] = HIDDEN
    from_accounts = not own and bool(automation.apprise_url(settings))
    return {
        "settings": view,
        "events": EVENTS,
        "apprise_available": automation.notifier.available(),
        "url_from_accounts": from_accounts,
        "next_maintenance": automation.next_maintenance(),
        "history": automation.history(),
    }


@router.get("/automation")
def automation_status(request: Request, reveal: bool = False) -> dict[str, Any]:
    svc = services(request)
    return _automation_view(svc, svc.automation.settings(), reveal)


@router.put("/automation")
def automation_save(request: Request, body: AutomationSettings) -> dict[str, Any]:
    svc = services(request)
    data = body.model_dump()
    if data["alerts"].get("url") == HIDDEN:  # the masked value came back unchanged
        data["alerts"].pop("url")
    try:
        saved = svc.automation.save(data)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return _automation_view(svc, saved)


@router.post("/automation/test")
def automation_test(request: Request) -> dict[str, Any]:
    ok, message = services(request).automation.test()
    return {"ok": ok, "message": _redactor(services(request))(message)}


@router.post("/automation/maintenance", status_code=202)
def automation_maintenance_now(request: Request) -> dict[str, Any]:
    """Run tonight's maintenance now."""
    started = services(request).automation.start_maintenance()
    if not started:
        raise HTTPException(409, "maintenance is already running")
    return {"started": True}


# -- containers ----------------------------------------------------------------
def _managed_container(name: str) -> dict[str, Any]:
    """The Saltbox-managed container called ``name``; 404 for anything else."""
    containers = _containers_or_none()
    if containers is None:
        raise HTTPException(503, "docker is not reachable from the daemon")
    for container in containers:
        if container["name"] == name and container["managed"]:
            return container
    raise HTTPException(404, f"no Saltbox container named {name}")


@router.post("/containers/{name}/{action}")
def container_act(request: Request, name: str, action: str) -> dict[str, Any]:
    """Start, stop or restart one of Saltbox's containers."""
    if action not in CONTAINER_ACTIONS:
        raise HTTPException(404, f"unknown action {action}")
    svc = services(request)
    _managed_container(name)
    try:
        container_action(name, action)
    except RuntimeError as error:
        raise HTTPException(502, str(error)) from error
    update = svc.updates.status_by_container().get(name)
    return _container_view(_managed_container(name), update)


@router.get("/containers/{name}/logs")
def container_log(request: Request, name: str, tail: int = 300) -> dict[str, Any]:
    _managed_container(name)
    try:
        lines = container_logs(name, tail)
    except RuntimeError as error:
        raise HTTPException(502, str(error)) from error
    redact = _redactor(services(request))
    return {"name": name, "lines": [redact(line) for line in lines]}


# -- app setup ---------------------------------------------------------------
def _app_setup(request: Request):
    from ..appsetup import AppSetup

    svc = services(request)
    factory = getattr(svc, "app_setup_factory", None) or AppSetup
    return factory(svc.layout)


@router.get("/setup")
def setup_status(request: Request, reveal: bool = False) -> dict[str, Any]:
    tasks = _app_setup(request).status()
    return _setup_view(services(request), tasks, reveal)


@router.post("/setup/apply")
def setup_apply(request: Request, reveal: bool = False) -> dict[str, Any]:
    tasks = _app_setup(request).apply()
    return _setup_view(services(request), tasks, reveal)


def _setup_view(svc, tasks: list, reveal: bool) -> dict[str, Any]:
    """Task list; API keys in the manual steps are hidden unless asked for."""
    from ..appsetup import summarize

    redact = _redactor(svc)
    views = []
    for task in tasks:
        view = task.as_dict()
        if not reveal:
            view["detail"] = redact(view["detail"])
        views.append(view)
    return {"summary": summarize(tasks), "tasks": views}


# -- jobs ------------------------------------------------------------------
class JobRequest(BaseModel):
    kind: str = "install"
    tags: list[str] = Field(default_factory=list)
    skip_tags: list[str] = Field(default_factory=list)
    extra_vars: list[str] = Field(default_factory=list)
    verbosity: int = 0
    no_cache: bool = False
    verbose: bool = False


@router.get("/jobs")
def jobs(request: Request, limit: int = 50) -> dict[str, Any]:
    svc = services(request)
    return {**_jobs_status(svc), "jobs": [_job_view(svc, j) for j in svc.runner.jobs(limit=limit)]}


@router.post("/jobs", status_code=202)
def start_job(request: Request, body: JobRequest) -> dict[str, Any]:
    svc = services(request)
    try:
        job = svc.jobs.start(
            body.kind,
            tags=body.tags,
            skip_tags=body.skip_tags,
            extra_vars=body.extra_vars,
            verbosity=body.verbosity,
            no_cache=body.no_cache,
            verbose=body.verbose,
        )
    except JobRunning as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return _job_view(svc, job)


@router.get("/jobs/{job_id}")
def job(request: Request, job_id: str) -> dict[str, Any]:
    svc = services(request)
    found = svc.runner.job(job_id)
    if found is None:
        raise HTTPException(404, "no such job")
    return _job_view(svc, found)


@router.get("/jobs/{job_id}/log")
def job_log(request: Request, job_id: str, offset: int = 0) -> dict[str, Any]:
    svc = services(request)
    found = svc.runner.job(job_id)
    if found is None:
        raise HTTPException(404, "no such job")
    text = svc.runner.log(job_id)
    return {
        "job": _job_view(svc, found),
        "offset": len(text),
        "text": _redactor(svc)(text[offset:]),
    }


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> dict[str, Any]:
    svc = services(request)
    if svc.runner.job(job_id) is None:
        raise HTTPException(404, "no such job")
    return {"cancelled": svc.jobs.cancel(job_id)}


@router.websocket("/jobs/{job_id}/stream")
async def stream_job(websocket: WebSocket, job_id: str) -> None:
    """Send the log as it grows, then the final job record.

    Messages: ``{"type": "log", "text": ...}`` chunks and one
    ``{"type": "done", "job": {...}}`` when the job has finished.
    """
    svc = websocket.app.state.services
    found = svc.runner.job(job_id)
    if found is None:
        await websocket.close(code=4004)
        return
    await websocket.accept()
    log_path = Path(found.log_path or svc.layout.jobs_dir / f"{job_id}.log")
    redact = _redactor(svc)
    offset = 0
    try:
        while True:
            chunk = await asyncio.to_thread(_read_from, log_path, offset)
            # Whole lines only while the job writes, so no secret is split across messages.
            whole = chunk[: chunk.rfind("\n") + 1]
            if whole:
                offset += len(whole.encode("utf-8"))
                await websocket.send_json({"type": "log", "text": redact(whole)})
            current = svc.runner.job(job_id)
            if current and current.status not in {"pending", "running"}:
                tail = await asyncio.to_thread(_read_from, log_path, offset)
                if tail:
                    await websocket.send_json({"type": "log", "text": redact(tail)})
                await websocket.send_json({"type": "done", "job": _job_view(svc, current)})
                break
            await asyncio.sleep(STREAM_POLL_SECONDS)
    except WebSocketDisconnect:
        return
    await websocket.close()


# -- helpers -----------------------------------------------------------------
REDACTOR_TTL_SECONDS = 60.0


def _redactor(svc) -> Redactor:
    """Every secret the server holds, to scrub from logs and instructions; cached a minute."""
    cached = svc.__dict__.get("_redactor")
    now = time.monotonic()
    if cached is not None and now - cached[0] < REDACTOR_TTL_SECONDS:
        return cached[1]
    from ..appsetup.discover import sabnzbd_api_key, xml_api_key

    values: list[str] = []
    texts = [svc.config.path(name) for name in CONFIG_FILES] + [svc.layout.inventory]
    for path in texts:
        try:
            values += secret_values(path.read_text(encoding="utf-8")).values()
        except OSError:
            continue
    appdata = svc.layout.appdata
    try:
        values += [xml_api_key(path) for path in appdata.glob("*/config.xml")]
        values += [sabnzbd_api_key(path) for path in appdata.glob("*/sabnzbd.ini")]
    except OSError:
        pass
    with contextlib.suppress(Exception):  # unreadable facts must not stop the page
        values += tree_secrets(read_all_facts(svc.layout, redact=False))
    redactor = Redactor(values)
    svc.__dict__["_redactor"] = (now, redactor)
    return redactor


def _job_view(svc, job) -> dict[str, Any]:
    """A job record with any secret on its command line (extra vars) hidden."""
    data = job.as_dict()
    redact = _redactor(svc)
    data["command_line"] = redact(data["command_line"])
    data["command"] = [redact(arg) for arg in data["command"]]
    return data


def _jobs_status(svc) -> dict[str, Any]:
    status = svc.jobs.status()
    current = svc.jobs.current
    status["current"] = _job_view(svc, current) if current is not None else None
    return status


def _unmask(text: str, saved_path: Path) -> str:
    """Put saved secrets back in place of the placeholders the browser was shown."""
    try:
        saved = saved_path.read_text(encoding="utf-8")
    except OSError:
        saved = ""
    try:
        return unmask_text(text, saved)
    except UnknownPlaceholder as error:
        raise HTTPException(400, str(error)) from error


def _coerce(value: Any) -> Any:
    """Strings from forms become YAML scalars; an empty string stays a string."""
    if isinstance(value, str) and value.strip():
        return coerce_scalar(value)
    return value


def _read_from(path: Path, offset: int) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _check_yaml(text: str) -> None:
    try:
        duplicates = find_duplicate_keys(text)
        load_text(text)
    except Exception as error:
        raise HTTPException(422, f"invalid YAML: {error}") from error
    if duplicates:
        raise HTTPException(422, f"duplicate keys: {', '.join(duplicates)}")


def _containers_or_none() -> list[dict[str, Any]] | None:
    try:
        return list_containers()
    except Exception:
        return None


def _container_summary(containers: list[dict[str, Any]] | None) -> dict[str, Any]:
    if containers is None:
        return {"available": False, "total": 0, "running": 0, "unhealthy": [], "stopped": []}
    managed = [c for c in containers if c["managed"]]
    return {
        "available": True,
        "total": len(managed),
        "running": sum(1 for c in managed if c["status"] == "running"),
        "unhealthy": [c["name"] for c in managed if c["health"] == "unhealthy"],
        "stopped": [c["name"] for c in managed if c["status"] != "running"],
    }


def _facts_for(svc, role: str) -> dict[str, Any]:
    try:
        data = read_role_facts(svc.layout, role)
    except OSError:
        return {}
    return {
        section: {k: redact_value(k, v) for k, v in values.items()}
        for section, values in data.items()
    }


def _git_describe(repo: Path) -> dict[str, str | None]:
    def run(*args: str) -> str | None:
        try:
            out = subprocess.run(
                # The daemon runs as root without sudo; git refuses a repository owned
                # by another user (the Saltbox user) unless it is marked safe.
                ["git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out.stdout.strip() or None if out.returncode == 0 else None

    return {
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": run("rev-parse", "--short", "HEAD"),
        "remote": run("remote", "get-url", "origin"),
    }
