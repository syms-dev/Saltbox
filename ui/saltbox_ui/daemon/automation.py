"""Alerts and nightly maintenance, run by the daemon in the background.

Alerts go out through Apprise, the notification tool Saltbox itself uses (its
``apprise:`` setting in accounts.yml is the default address). The monitor
looks every minute and tells you when something *changes*: an app turns
unhealthy or stops, a job fails, a disk fills up, updates arrive, the VPN goes
down or qBittorrent leaves it. Each alert has a one-hour cooldown so a flapping
container cannot flood your phone.

Nightly maintenance, when switched on, checks for new images at the chosen
time, optionally runs ``sb update`` first, updates every app that has a new
image except the ones you excluded, and sends one summary.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger("saltbox_ui.automation")

SETTINGS_FILE = "automation.json"
HISTORY_FILE = "alerts.jsonl"
HISTORY_KEEP = 200
COOLDOWN_SECONDS = 3600
DISK_ALERT_PERCENT = 90
DISK_REARM_PERCENT = 85
MAINTENANCE_WINDOW_MINUTES = 120
APPRISE_CANDIDATES = ("/srv/ansible/venv/bin/apprise", "/usr/local/bin/apprise")

EVENTS = {
    "unhealthy": "An app turns unhealthy or stops",
    "job_failed": "A job fails",
    "disk": "A disk is over 90% full",
    "updates": "New app or Saltbox updates are available",
    "vpn": "The VPN goes down or qBittorrent leaves it",
    "maintenance": "Nightly maintenance finishes",
}

DEFAULTS: dict[str, Any] = {
    "alerts": {"enabled": False, "url": "", "events": dict.fromkeys(EVENTS, True)},
    "maintenance": {"enabled": False, "time": "04:00", "saltbox": False, "exclude": []},
}

Runner = Callable[[list[str]], tuple[int, str]]


def find_apprise() -> str | None:
    found = shutil.which("apprise")
    if found:
        return found
    return next((path for path in APPRISE_CANDIDATES if os.access(path, os.X_OK)), None)


def _run(args: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(args, capture_output=True, text=True, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return done.returncode, (done.stdout + done.stderr).strip()


class Notifier:
    """Sends through the Apprise CLI. The URL goes in a private file, never on argv."""

    def __init__(self, workdir: Path, runner: Runner | None = None, binary: str | None = None):
        self.workdir = workdir
        self.runner = runner or _run
        self.binary = binary

    def available(self) -> bool:
        return (self.binary or find_apprise()) is not None

    def send(self, url: str, title: str, body: str) -> tuple[bool, str]:
        binary = self.binary or find_apprise()
        if binary is None:
            return False, "Apprise is not installed (Saltbox installs it in /srv/ansible/venv)"
        if not url.strip():
            return False, "no Apprise URL set"
        self.workdir.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix="apprise-", suffix=".txt", dir=self.workdir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(url.strip() + "\n")
            code, output = self.runner([binary, "-t", title, "-b", body, "--config", path])
        finally:
            Path(path).unlink(missing_ok=True)
        return code == 0, output[-500:] if code != 0 else "sent"


class AutomationService:
    def __init__(
        self,
        svc: Any,
        *,
        notifier: Notifier | None = None,
        containers: Callable[[], list[dict[str, Any]]] | None = None,
        disks: Callable[[], list[dict[str, Any]]] | None = None,
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], None] = time.sleep,
        interval: float = 60,
    ):
        self.svc = svc
        state = svc.layout.state_dir
        self.settings_path = state / SETTINGS_FILE
        self.history_path = state / HISTORY_FILE
        self.notifier = notifier or Notifier(state / "tmp")
        self.containers = containers
        self.disks = disks
        self.clock = clock
        self.sleep = sleep
        self.interval = interval
        self._lock = threading.Lock()
        self._last_sent: dict[str, float] = {}
        self._baseline = True
        self._down: set[str] = set()
        self._full: set[str] = set()
        self._updates_seen: set[str] = set()
        self._vpn_problems: set[str] = set()
        self._maintenance_job: str | None = None
        self._maintenance_thread: threading.Thread | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- settings ----------------------------------------------------------------------
    def settings(self) -> dict[str, Any]:
        try:
            saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        merged = json.loads(json.dumps(DEFAULTS))
        for section, values in (saved or {}).items():
            if section in merged and isinstance(values, dict):
                for key, value in values.items():
                    if key == "events" and isinstance(value, dict):
                        merged[section]["events"].update(
                            {k: bool(v) for k, v in value.items() if k in EVENTS}
                        )
                    elif key in merged[section] or key in ("last_run",):
                        merged[section][key] = value
        return merged

    def save(self, settings: dict[str, Any]) -> dict[str, Any]:
        current = self.settings()
        for section in ("alerts", "maintenance"):
            for key, value in (settings.get(section) or {}).items():
                if key in DEFAULTS[section]:
                    current[section][key] = value
        time_text = str(current["maintenance"]["time"])
        try:
            datetime.strptime(time_text, "%H:%M")
        except ValueError as error:
            raise ValueError(f"maintenance time must look like 04:00, not {time_text!r}") from error
        self._write(current)
        return current

    def _write(self, settings: dict[str, Any]) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.settings_path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # holds the Apprise URL
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=1)
        tmp.replace(self.settings_path)

    def apprise_url(self, settings: dict[str, Any] | None = None) -> str:
        """The URL set here, or else the ``apprise:`` value from accounts.yml."""
        url = str((settings or self.settings())["alerts"]["url"] or "").strip()
        if url:
            return url
        try:
            return str(self.svc.config.get("accounts", "apprise") or "").strip()
        except Exception:  # missing accounts.yml
            return ""

    # -- alerts ------------------------------------------------------------------------
    def history(self, limit: int = 30) -> list[dict[str, Any]]:
        try:
            lines = self.history_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        entries = []
        for line in reversed(lines[-limit:]):
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
        return entries

    def _record(self, entry: dict[str, Any]) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lines = self.history_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        lines = [*lines[-(HISTORY_KEEP - 1) :], json.dumps(entry)]
        self.history_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def alert(self, event: str, title: str, body: str, *, key: str | None = None) -> bool:
        """Send one alert if alerts and this event are on and its cooldown has passed."""
        settings = self.settings()
        alerts = settings["alerts"]
        key = key or f"{event}:{title}"
        now = time.time()
        with self._lock:
            if now - self._last_sent.get(key, 0) < COOLDOWN_SECONDS:
                return False
            self._last_sent[key] = now
        entry = {"at": now, "event": event, "title": title, "body": body, "sent": False}
        if alerts["enabled"] and alerts["events"].get(event, False):
            ok, message = self.notifier.send(self.apprise_url(settings), title, body)
            entry["sent"], entry["result"] = ok, message
            if not ok:
                log.warning("alert not sent: %s", message)
        self._record(entry)
        return bool(entry["sent"])

    def test(self) -> tuple[bool, str]:
        settings = self.settings()
        return self.notifier.send(
            self.apprise_url(settings),
            "Saltbox test alert",
            "Alerts from your Saltbox server will arrive here.",
        )

    # -- monitor ----------------------------------------------------------------------------
    def tick(self) -> None:
        """One look at the server: alert on what changed since the last look."""
        containers = self._containers()
        if containers is not None:
            self._check_containers(containers)
            self._check_vpn(containers)
        self._check_disks()
        self._check_updates()
        self._baseline = False
        self._maybe_maintenance()

    def _containers(self) -> list[dict[str, Any]] | None:
        try:
            if self.containers is not None:
                return self.containers()
            from ..state.containers import list_containers

            return list_containers()
        except Exception:
            return None

    def _check_containers(self, containers: list[dict[str, Any]]) -> None:
        managed = [c for c in containers if c.get("managed")]
        down = {
            c["name"]: ("unhealthy" if c.get("health") == "unhealthy" else "stopped")
            for c in managed
            if c.get("health") == "unhealthy" or c.get("status") != "running"
        }
        if not self._baseline:
            for name, state in down.items():
                if name not in self._down:
                    self.alert(
                        "unhealthy",
                        f"{name} is {state}",
                        f"{name} on your Saltbox server is {state}. Restart it from the web app.",
                    )
            for name in self._down - set(down):
                self.alert("unhealthy", f"{name} is running again", f"{name} recovered.")
        self._down = set(down)

    def _check_vpn(self, containers: list[dict[str, Any]]) -> None:
        by_name = {c["name"]: c for c in containers}
        gluetun = by_name.get("gluetun")
        problems: dict[str, tuple[str, str]] = {}
        if gluetun is not None and gluetun.get("status") != "running":
            problems["down"] = (
                "The VPN is down",
                "Gluetun is not running; downloads through it stopped.",
            )
        qbit = by_name.get("qbittorrent")
        if (
            gluetun is not None
            and qbit is not None
            and qbit.get("network_mode") != "container:gluetun"
        ):
            problems["leak"] = (
                "qBittorrent is not behind the VPN",
                "Its traffic leaves through your home connection.",
            )
        if not self._baseline:
            for key, (title, body) in problems.items():
                if key not in self._vpn_problems:
                    self.alert("vpn", title, body)
        self._vpn_problems = set(problems)

    def _check_disks(self) -> None:
        try:
            if self.disks is not None:
                disks = self.disks()
            else:
                from ..state.host import disk_usage

                disks = disk_usage()
        except Exception:
            return
        for disk in disks:
            path, percent = disk["path"], float(disk["percent"])
            if percent >= DISK_ALERT_PERCENT and path not in self._full:
                self._full.add(path)
                self.alert(
                    "disk",
                    f"{path} is {percent:.0f}% full",
                    f"{path} on your Saltbox server is {percent:.0f}% full.",
                )
            elif percent < DISK_REARM_PERCENT:
                self._full.discard(path)

    def _check_updates(self) -> None:
        cached = self.svc.updates.cached()
        pending = {
            name
            for status in cached.get("images", {}).values()
            if status.get("status") == "update"
            for name in status.get("containers", [])
        }
        pending |= {
            f"saltbox:{repo['name']}"
            for repo in cached.get("repos", [])
            if repo.get("status") == "update"
        }
        new = pending - self._updates_seen
        if new and not self._baseline:
            apps = sorted(n for n in new if not n.startswith("saltbox:"))
            parts = [f"apps: {', '.join(apps)}"] if apps else []
            if any(n.startswith("saltbox:") for n in new):
                parts.append("Saltbox itself")
            self.alert("updates", "Updates available", "New versions for " + "; ".join(parts) + ".")
        self._updates_seen = pending

    # -- jobs ----------------------------------------------------------------------------------
    def on_job_finished(self, job: Any) -> None:
        if job.id == self._maintenance_job:
            return  # the maintenance run sends its own summary
        if job.status == "failed":
            title = " ".join(Path(job.command[0]).name.split()) + " " + " ".join(job.command[1:])
            self.alert(
                "job_failed",
                f"Job failed: {title}",
                f"{title} failed with exit code {job.returncode}. See Activity in the web app.",
                key=f"job:{job.id}",
            )

    # -- maintenance ------------------------------------------------------------------------------
    def next_maintenance(self) -> str | None:
        settings = self.settings()["maintenance"]
        if not settings["enabled"]:
            return None
        hour, minute = (int(x) for x in str(settings["time"]).split(":"))
        now = self.clock()
        at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        last = (settings.get("last_run") or {}).get("date")
        if at <= now and (last == now.date().isoformat() or now - at > self._window()):
            at += timedelta(days=1)
        return at.isoformat(timespec="minutes")

    def _window(self) -> timedelta:
        return timedelta(minutes=MAINTENANCE_WINDOW_MINUTES)

    def _maybe_maintenance(self) -> None:
        settings = self.settings()["maintenance"]
        if not settings["enabled"]:
            return
        now = self.clock()
        hour, minute = (int(x) for x in str(settings["time"]).split(":"))
        at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        last = (settings.get("last_run") or {}).get("date")
        running = self._maintenance_thread is not None and self._maintenance_thread.is_alive()
        if at <= now <= at + self._window() and last != now.date().isoformat() and not running:
            self.start_maintenance()

    def start_maintenance(self) -> bool:
        """Run maintenance in its own thread, so the monitor keeps looking meanwhile."""
        if self._maintenance_thread is not None and self._maintenance_thread.is_alive():
            return False
        self._maintenance_thread = threading.Thread(
            target=self.run_maintenance, name="maintenance", daemon=True
        )
        self._maintenance_thread.start()
        return True

    def run_maintenance(self, *, wait_seconds: float = 6 * 3600) -> dict[str, Any]:
        """Check, update what has a new image (minus exclusions), record and report."""
        from . import routes

        svc = self.svc
        settings = self.settings()
        maintenance = settings["maintenance"]
        today = self.clock().date().isoformat()
        record: dict[str, Any] = {"date": today, "started_at": time.time(), "steps": []}
        self._save_last_run(record)  # claim tonight before anything slow
        svc.updates.refresh(wait=True)
        cached = svc.updates.cached()

        if maintenance["saltbox"] and any(
            r.get("status") == "update" for r in cached.get("repos", [])
        ):
            record["steps"].append(
                self._run_job(lambda: svc.jobs.start("update"), "sb update", wait_seconds)
            )
            svc.updates.refresh(wait=True)
            cached = svc.updates.cached()

        excluded = set(maintenance.get("exclude") or [])
        pending = {
            name
            for status in cached.get("images", {}).values()
            if status.get("status") == "update"
            for name in status.get("containers", [])
        }
        apps = [
            app
            for app in svc.catalog.apps()
            if app.role not in excluded
            and pending
            & set(svc.inventory.instances(app.role, app.default_instances or [app.role]))
        ]
        if apps:
            titles = ", ".join(app.title for app in apps)

            def start() -> Any:
                view = routes._start_update(svc, apps)
                return svc.runner.job(view["id"])

            record["steps"].append(self._run_job(start, f"update {titles}", wait_seconds))
        record["finished_at"] = time.time()
        record["status"] = (
            "failed"
            if any(step["status"] != "succeeded" for step in record["steps"])
            else ("nothing" if not record["steps"] else "succeeded")
        )
        self._save_last_run(record)
        if record["steps"]:
            lines = [f"{step['what']}: {step['status']}" for step in record["steps"]]
            title = "Nightly maintenance " + ("failed" if record["status"] == "failed" else "done")
            self.alert("maintenance", title, "\n".join(lines), key=f"maintenance:{today}")
        return record

    def _run_job(self, start: Callable[[], Any], what: str, wait_seconds: float) -> dict[str, Any]:
        from ..runner import JobRunning

        try:
            job = start()
        except (JobRunning, Exception) as error:  # a job already running, docker down, ...
            return {"what": what, "status": "skipped", "detail": str(error)}
        self._maintenance_job = job.id
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            current = self.svc.runner.job(job.id)
            if current is not None and current.status not in ("pending", "running"):
                return {"what": what, "status": current.status, "job": job.id}
            self.sleep(2)
        return {"what": what, "status": "timed out", "job": job.id}

    def _save_last_run(self, record: dict[str, Any]) -> None:
        settings = self.settings()
        settings["maintenance"]["last_run"] = record
        self._write(settings)

    # -- thread -----------------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="automation", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # never let one bad look stop the monitor
                log.exception("automation tick failed")
            self._stop.wait(self.interval)
