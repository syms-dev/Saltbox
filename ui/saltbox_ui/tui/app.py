"""The installer application.

A linear wizard over ``StepScreen`` subclasses. The app owns the
``InstallerSession`` and knows how to resume a plan that stopped part way,
for example because the kernel role rebooted the host during preinstall.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

from textual.app import App
from textual.binding import Binding

from ..installer import InstallerSession
from ..installer.preflight import Probe
from ..layout import Layout
from .installer.screens import (
    AccountScreen,
    AdvancedScreen,
    AppsScreen,
    DnsScreen,
    DoneScreen,
    InstallScreen,
    PreflightScreen,
    PreinstallScreen,
    ReviewScreen,
    StorageScreen,
    WelcomeScreen,
)
from .widgets import StepScreen

STEPS: list[type[StepScreen]] = [
    WelcomeScreen,
    PreflightScreen,
    AccountScreen,
    DnsScreen,
    AppsScreen,
    AdvancedScreen,
    ReviewScreen,
    PreinstallScreen,
    StorageScreen,
    InstallScreen,
    DoneScreen,
]
PHASE_STEP = {
    "preinstall": PreinstallScreen,
    "storage": StorageScreen,
    "install": InstallScreen,
    "done": DoneScreen,
}
PRESERVED_ENV = (
    "SALTBOX_REPO",
    "SALTBOX_APPDATA",
    "SB_BINARY",
    "SALTBOX_UI_STATE",
    "RCLONE_BINARY",
)


class InstallerApp(App[None]):
    CSS_PATH = Path(__file__).with_name("styles.tcss")
    TITLE = "Saltbox installer"
    BINDINGS = [Binding("ctrl+q", "quit_app", "Quit", priority=True)]

    def __init__(
        self,
        session: InstallerSession,
        *,
        probe_factory: Callable[[Layout], Probe] | None = None,
        auto_resume: bool = True,
    ) -> None:
        super().__init__()
        self.session = session
        self.probe_factory = probe_factory or Probe.from_host
        self.auto_resume = auto_resume
        self.step_index = 0

    @property
    def plan(self):
        return self.session.plan

    def on_mount(self) -> None:
        if self.auto_resume and self.session.resumable:
            self.session.resume_after_reboot()
        self.show_step(0, push=True)

    def step_for_phase(self) -> int:
        screen = PHASE_STEP.get(self.session.plan.phase)
        return STEPS.index(screen) if screen else 0

    def show_step(self, index: int, *, push: bool = False) -> None:
        index = max(0, min(index, len(STEPS) - 1))
        self.step_index = index
        screen = STEPS[index](index, len(STEPS))
        if push:
            self.push_screen(screen)
        else:
            self.switch_screen(screen)

    def on_step_screen_navigate(self, message: StepScreen.Navigate) -> None:
        target = self.step_index + message.direction
        if target >= len(STEPS):
            self.exit()
            return
        self.show_step(target)

    def resume(self) -> None:
        self.show_step(self.step_for_phase())

    def action_quit_app(self) -> None:
        self.session.save()
        self.exit()


def ensure_root(argv: list[str]) -> None:
    """Re-exec through sudo when not root, like sb does, keeping engine env vars."""
    if os.geteuid() == 0 or os.environ.get("SALTBOX_UI_NO_SUDO"):
        return
    keep = ",".join(k for k in PRESERVED_ENV if k in os.environ)
    command = ["sudo"]
    if keep:
        command.append(f"--preserve-env={keep}")
    command += [sys.executable, "-m", "saltbox_ui.tui", *argv]
    os.execvp("sudo", command)


def run_installer(layout: Layout | None = None) -> None:
    layout = layout or Layout.from_env()
    session = InstallerSession(layout)
    InstallerApp(session).run()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--help" in args or "-h" in args:
        print(
            "saltbox-ui [--installer] [--serve [HOST:PORT]]\n\nRuns the Saltbox installer wizard."
        )
        return 0
    ensure_root(args)
    if "--serve" in args:
        return serve(args)
    run_installer()
    return 0


def serve(args: list[str]) -> int:
    """Serve the TUI to a browser with textual-serve, for people who want a mouse."""
    try:
        from textual_serve.server import Server
    except ImportError:
        print("textual-serve is not installed; pip install saltbox-ui[serve]", file=sys.stderr)
        return 1
    index = args.index("--serve")
    host, port = "127.0.0.1", 8700
    if index + 1 < len(args) and ":" in args[index + 1]:
        host, port_text = args[index + 1].rsplit(":", 1)
        port = int(port_text)
    server = Server(f"{sys.executable} -m saltbox_ui.tui", host=host, port=port, title="Saltbox")
    server.serve()
    return 0
