"""HTTP and WebSocket routes.

Everything is a thin call into the engine. Writes go through the same
``ConfigService`` and ``Inventory`` the TUI and ``sbx`` use, so a file edited
in the browser keeps its comments and passes the same validation.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .. import __version__
from ..config.service import CONFIG_FILES
from ..runner import JobRunning
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
    }


@router.get("/overview")
def overview(request: Request) -> dict[str, Any]:
    svc = services(request)
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
            "installed": layout.facts_dir.exists(),
            "configs_present": layout.config_file("accounts").exists(),
            "roles_with_facts": sorted(
                p.stem for p in layout.facts_dir.glob("*.ini") if layout.facts_dir.exists()
            ),
        },
        "containers": _container_summary(containers),
        "services": read_motd_services(layout),
        "jobs": {
            **svc.jobs.status(),
            "recent": [j.as_dict() for j in svc.runner.jobs(limit=5)],
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
    result = []
    for app in svc.catalog.apps(include_hidden=all):
        instances = svc.inventory.instances(app.role, app.default_instances or [app.role])
        data = app.as_dict()
        data["instances"] = instances
        data["installed"] = (svc.layout.facts_dir / f"{app.role}.ini").exists()
        data["containers"] = [
            {"name": name, "status": by_name[name]["status"], "health": by_name[name]["health"]}
            for name in instances
            if name in by_name
        ]
        result.append(data)
    return result


@router.get("/apps/{repo}/{role}")
def app_detail(request: Request, repo: str, role: str) -> dict[str, Any]:
    svc = services(request)
    app = svc.catalog.app(role, repo)
    if app is None:
        raise HTTPException(404, f"unknown app {repo}/{role}")
    defaults = svc.catalog.defaults(role, repo)
    instances = svc.inventory.instances(role, app.default_instances or [role])
    return {
        "app": app.as_dict(),
        "instances": instances,
        "fields": [f.as_dict() for f in defaults.visible()] if defaults else [],
        "overrides": svc.inventory.overrides_for(role, instances),
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
def config_file(request: Request, name: str) -> dict[str, Any]:
    svc = services(request)
    if name not in CONFIG_FILES:
        raise HTTPException(404, f"unknown config file {name}")
    path = svc.config.path(name)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if not text:
        default = svc.config.default_path(name)
        text = default.read_text(encoding="utf-8") if default and default.exists() else ""
    return {
        "name": name,
        "path": str(path),
        "source": svc.config.source(name),
        "text": text,
        "data": svc.config.load_plain(name) if (path.exists() or text) else {},
        "issues": [i.as_dict() for i in svc.config.validate(name)],
    }


class ConfigText(BaseModel):
    text: str


@router.put("/config/{name}")
def write_config_file(request: Request, name: str, body: ConfigText) -> dict[str, Any]:
    svc = services(request)
    if name not in CONFIG_FILES:
        raise HTTPException(404, f"unknown config file {name}")
    _check_yaml(body.text)
    path = svc.config.path(name)
    write_atomic(path, body.text if body.text.endswith("\n") else body.text + "\n")
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
def inventory(request: Request) -> dict[str, Any]:
    svc = services(request)
    path = svc.layout.inventory
    return {
        "path": str(path),
        "text": path.read_text(encoding="utf-8") if path.exists() else "",
        "data": svc.inventory.as_dict(),
        "issues": [i.as_dict() for i in svc.config.validate_inventory()],
    }


@router.put("/inventory")
def write_inventory(request: Request, body: ConfigText) -> dict[str, Any]:
    svc = services(request)
    _check_yaml(body.text)
    write_atomic(svc.layout.inventory, body.text if body.text.endswith("\n") else body.text + "\n")
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
    return {**svc.jobs.status(), "jobs": [j.as_dict() for j in svc.runner.jobs(limit=limit)]}


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
    return job.as_dict()


@router.get("/jobs/{job_id}")
def job(request: Request, job_id: str) -> dict[str, Any]:
    found = services(request).runner.job(job_id)
    if found is None:
        raise HTTPException(404, "no such job")
    return found.as_dict()


@router.get("/jobs/{job_id}/log")
def job_log(request: Request, job_id: str, offset: int = 0) -> dict[str, Any]:
    svc = services(request)
    found = svc.runner.job(job_id)
    if found is None:
        raise HTTPException(404, "no such job")
    text = svc.runner.log(job_id)
    return {"job": found.as_dict(), "offset": len(text), "text": text[offset:]}


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
    offset = 0
    try:
        while True:
            chunk = await asyncio.to_thread(_read_from, log_path, offset)
            if chunk:
                offset += len(chunk.encode("utf-8"))
                await websocket.send_json({"type": "log", "text": chunk})
            current = svc.runner.job(job_id)
            if current and current.status not in {"pending", "running"}:
                tail = await asyncio.to_thread(_read_from, log_path, offset)
                if tail:
                    await websocket.send_json({"type": "log", "text": tail})
                await websocket.send_json({"type": "done", "job": current.as_dict()})
                break
            await asyncio.sleep(STREAM_POLL_SECONDS)
    except WebSocketDisconnect:
        return
    await websocket.close()


# -- helpers -----------------------------------------------------------------
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
                ["git", "-C", str(repo), *args],
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
