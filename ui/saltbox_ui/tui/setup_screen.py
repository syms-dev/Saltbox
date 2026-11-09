"""Connect the apps after the install: one screen, safe to run any time."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Static

from ..appsetup import AppSetup, Task, summarize
from ..layout import Layout
from .widgets import CheckRow


class SetupScreen(Screen):
    """Lists every connection, checks it, and applies the missing ones."""

    def __init__(self, setup: AppSetup, *, on_close: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.setup = setup
        self.on_close = on_close
        self.rows: dict[str, CheckRow] = {}
        self.tasks: list[Task] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="step-header"):
            yield Static("Saltbox · Connect your apps", classes="title")
        with VerticalScroll(id="body"):
            yield Static(
                "Links Sonarr, Radarr and Lidarr to qBittorrent, Autoscan and Prowlarr, and adds "
                "your Plex libraries, with the settings the Saltbox docs recommend. It only adds "
                "what's missing, so it's safe to run again.",
                classes="lede",
            )
            yield Vertical(id="setup-tasks")
            yield Static("Checking your apps…", id="setup-summary", classes="hint")
        with Horizontal(id="nav"):
            yield Button("Close", id="setup_close")
            yield Static("", classes="spacer")
            yield Button("Check again", id="setup_check")
            yield Button("Connect everything", id="setup_apply", variant="primary")

    def on_mount(self) -> None:
        self._busy(True)
        self.check()

    def _busy(self, busy: bool) -> None:
        self.query_one("#setup_apply", Button).disabled = busy
        self.query_one("#setup_check", Button).disabled = busy

    # -- workers -----------------------------------------------------------------
    @work(thread=True, exclusive=True)
    def check(self) -> None:
        try:
            tasks = self.setup.status()
        except Exception as error:  # the screen must stay usable whatever breaks
            self.app.call_from_thread(self._failed, str(error))
            return
        self.app.call_from_thread(self._show_tasks, tasks)

    @work(thread=True, exclusive=True)
    def apply(self) -> None:
        try:
            tasks = self.setup.apply(
                on_task=lambda task: self.app.call_from_thread(self._update_row, task)
            )
        except Exception as error:
            self.app.call_from_thread(self._failed, str(error))
            return
        self.app.call_from_thread(self._show_tasks, tasks)

    # -- rendering -----------------------------------------------------------------
    def _show_tasks(self, tasks: list[Task]) -> None:
        self.tasks = tasks
        box = self.query_one("#setup-tasks", Vertical)
        box.remove_children()
        self.rows = {}
        rows = []
        for task in tasks:
            row = CheckRow(task.id, f"{task.app}: {task.title}", task.status, task.detail)
            self.rows[task.id] = row
            rows.append(row)
        box.mount_all(rows)
        self._summary()
        self._busy(False)
        self.query_one("#setup_apply", Button).disabled = not any(
            t.status in ("todo", "error") and t.apply is not None for t in tasks
        )

    def _update_row(self, task: Task) -> None:
        row = self.rows.get(task.id)
        if row is not None:
            row.update(task.status, task.detail)

    def _summary(self) -> None:
        counts = summarize(self.tasks)
        if not self.tasks:
            text = "No apps to connect were found. Install Sonarr, Radarr or Plex first."
        else:
            parts = [f"{counts['done']} connected"]
            if counts["todo"]:
                parts.append(f"{counts['todo']} to connect")
            if counts["manual"]:
                parts.append(f"{counts['manual']} for you to do by hand")
            if counts["error"]:
                parts.append(f"{counts['error']} failed")
            text = ", ".join(parts) + "."
        widget = self.query_one("#setup-summary", Static)
        widget.update(text)
        widget.set_classes("error" if counts["error"] else ("ok" if not counts["todo"] else "hint"))

    def _failed(self, message: str) -> None:
        widget = self.query_one("#setup-summary", Static)
        widget.update(f"Setup could not run: {message}")
        widget.set_classes("error")
        self._busy(False)

    # -- buttons -----------------------------------------------------------------
    @on(Button.Pressed, "#setup_apply")
    def _apply(self) -> None:
        self._busy(True)
        self.query_one("#setup-summary", Static).update("Connecting…")
        for task in self.tasks:
            row = self.rows.get(task.id)
            if row is not None and task.status in ("todo", "error") and task.apply is not None:
                row.update("running", "connecting…")
        self.apply()

    @on(Button.Pressed, "#setup_check")
    def _check(self) -> None:
        self._busy(True)
        self.query_one("#setup-summary", Static).update("Checking your apps…")
        self.check()

    @on(Button.Pressed, "#setup_close")
    def _close(self) -> None:
        if self.on_close is not None:
            self.on_close()
        else:
            self.app.pop_screen()


class SetupApp(App[None]):
    """``saltbox-ui --setup``: the setup screen on its own."""

    CSS_PATH = Path(__file__).with_name("styles.tcss")
    TITLE = "Saltbox setup"
    BINDINGS = [Binding("ctrl+q", "quit", "Quit", priority=True)]

    def __init__(self, setup: AppSetup) -> None:
        super().__init__()
        self.setup = setup

    def on_mount(self) -> None:
        self.push_screen(SetupScreen(self.setup, on_close=self.exit))


def run_setup(layout: Layout | None = None) -> None:
    SetupApp(AppSetup(layout or Layout.from_env())).run()
