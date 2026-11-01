"""The installer session: plan persistence plus the steps that run ``sb``.

Phases, in order:

- ``collect``: answers are gathered, nothing has been written.
- ``preinstall``: config written and validated, ``sb install preinstall`` ran
  or is running. The kernel role may reboot the host in the middle of it.
- ``storage``: the Saltbox user exists, rclone remotes can be configured as
  that user.
- ``install``: the main tag run.
- ``done``.

A plan file under the state directory records the phase, so starting the
installer again after a reboot picks up where it stopped.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..catalog import Catalog
from ..config import ConfigService, Inventory
from ..layout import Layout
from ..rclone import RcloneService
from ..runner import Job, SbRunner
from ..schema import Issue
from .plan import InstallPlan

LineCallback = Callable[[str], None]
PLAN_FILENAME = "install-plan.json"


class InstallerSession:
    def __init__(
        self,
        layout: Layout,
        *,
        plan: InstallPlan | None = None,
        runner: SbRunner | None = None,
        config: ConfigService | None = None,
        rclone_factory: Callable[[str], RcloneService] | None = None,
    ):
        self.layout = layout
        self.plan_path = layout.state_dir / PLAN_FILENAME
        self.plan = plan or self._load_plan()
        self.runner = runner or SbRunner(layout)
        self.config = config or ConfigService(layout)
        self.inventory = Inventory(layout.inventory)
        self.catalog = Catalog(layout)
        self._rclone_factory = rclone_factory or (
            lambda user: RcloneService(layout.rclone_binary, user=user)
        )

    # -- plan ------------------------------------------------------------------
    def _load_plan(self) -> InstallPlan:
        if self.plan_path.exists():
            try:
                return InstallPlan.load(self.plan_path)
            except (ValueError, TypeError):
                pass
        return InstallPlan()

    @property
    def resumable(self) -> bool:
        return self.plan_path.exists() and self.plan.phase not in {"collect", "done"}

    def save(self) -> None:
        self.plan.save(self.plan_path)

    def discard(self) -> None:
        if self.plan_path.exists():
            self.plan_path.unlink()
        self.plan = InstallPlan()

    def set_phase(self, phase: str) -> None:
        self.plan.phase = phase
        self.save()

    # -- config ----------------------------------------------------------------
    def ensure_config_files(self) -> list[str]:
        created = []
        for name in (
            "accounts",
            "settings",
            "adv_settings",
            "backup_config",
            "providers",
            "hetzner_vlan",
        ):
            if self.config.ensure_exists(name):
                created.append(name)
        return created

    def apply_config(self) -> list[str]:
        self.ensure_config_files()
        return self.plan.apply(self.config, self.inventory, self.catalog.profiles)

    def validate(self, *, api_checks: bool = False) -> dict[str, list[Issue]]:
        results = self.config.validate_all(api_checks=api_checks)
        return {name: issues for name, issues in results.items() if issues}

    @staticmethod
    def has_errors(results: dict[str, list[Issue]]) -> bool:
        return any(i.level == "error" for issues in results.values() for i in issues)

    # -- rclone ----------------------------------------------------------------
    def rclone(self) -> RcloneService:
        return self._rclone_factory(self.plan.user_name)

    # -- steps -----------------------------------------------------------------
    def run_preinstall(self, on_line: LineCallback | None = None) -> Job:
        self.plan.preinstall_started_at = time.time()
        self.set_phase("preinstall")
        job = self.runner.install(["preinstall"], on_line=on_line)
        self.plan.jobs["preinstall"] = job.id
        if job.status == "succeeded":
            self.set_phase("storage")
        else:
            self.save()
        return job

    def preinstall_rebooted(self) -> bool:
        """True when the host booted after preinstall started (the kernel role reboots)."""
        started = self.plan.preinstall_started_at
        if not started:
            return False
        return boot_time() > started

    def resume_after_reboot(self) -> bool:
        """Advance past preinstall when a reboot interrupted it. Returns True if advanced."""
        if self.plan.phase == "preinstall" and self.preinstall_rebooted():
            self.plan.notes.append("preinstall was interrupted by a reboot; continuing")
            self.set_phase("storage")
            return True
        return False

    def run_install(self, on_line: LineCallback | None = None) -> Job:
        self.set_phase("install")
        tags = self.plan.install_tags()
        job = self.runner.install(tags, on_line=on_line)
        self.plan.jobs["install"] = job.id
        if job.status == "succeeded":
            self.set_phase("done")
        else:
            self.save()
        return job

    def enable_web(self) -> dict[str, Any]:
        """Set up the web face for this install; replaceable in tests."""
        from ..daemon.install import enable_web

        result = enable_web(self.layout)
        self.plan.notes.append(f"web UI enabled at {result['url']}")
        self.save()
        return result

    def run_tag(self, tags: list[str], on_line: LineCallback | None = None) -> Job:
        job = self.runner.install(tags, on_line=on_line)
        self.plan.jobs[",".join(tags)] = job.id
        self.save()
        return job


def boot_time() -> float:
    try:
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith("btime "):
                return float(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0.0
