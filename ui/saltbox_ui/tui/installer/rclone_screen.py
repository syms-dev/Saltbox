"""Modal that walks through rclone's questions for one new remote."""

from __future__ import annotations

from typing import Any

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, RadioButton, RadioSet, Static

from ...rclone import Question, RcloneError, RcloneService


class RcloneQuestionScreen(ModalScreen[dict[str, Any] | None]):
    """Create ``name`` of ``remote_type`` by answering rclone one question at a time.

    Dismisses with ``{"created": True, "dirs": [...]}`` on success, or ``None``
    when cancelled.
    """

    def __init__(self, service: RcloneService, name: str, remote_type: str) -> None:
        super().__init__()
        self.service = service
        self.remote_name = name
        self.remote_type = remote_type
        self.question: Question | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(
                f"New rclone remote: {self.remote_name} ({self.remote_type})", classes="section"
            )
            yield Static("Asking rclone…", id="qname")
            yield Static("", id="help", classes="help")
            yield Static("", id="authorize", classes="authorize")
            yield RadioSet(id="choices")
            yield Input(id="answer", placeholder="answer")
            yield Static("", id="error", classes="error")
            with Horizontal(id="dialog-nav"):
                yield Button("Cancel", id="cancel")
                yield Button("Use default", id="default")
                yield Button("Answer", id="submit", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#choices", RadioSet).display = False
        self.query_one("#authorize", Static).display = False
        self.advance(None, first=True)

    # -- state machine -------------------------------------------------------
    @work(thread=True, exclusive=True)
    def advance(self, answer: str | None, *, first: bool = False) -> None:
        try:
            if first:
                question = self.service.create_step(self.remote_name, self.remote_type)
            else:
                assert self.question is not None
                question = self.service.create_step(
                    self.remote_name,
                    self.remote_type,
                    state=self.question.state,
                    result="" if answer is None else answer,
                )
            while question is not None and question.name == "config_is_local":
                question = self.service.create_step(
                    self.remote_name, self.remote_type, state=question.state, result="false"
                )
        except RcloneError as error:
            self.app.call_from_thread(self.show_error, str(error))
            return
        if question is None:
            self.app.call_from_thread(self.finish)
        else:
            self.app.call_from_thread(self.show_question, question)

    def show_error(self, message: str) -> None:
        self.query_one("#error", Static).update(message)

    def show_question(self, question: Question) -> None:
        self.question = question
        self.query_one("#error", Static).update(question.error or "")
        self.query_one("#qname", Static).update(f"Option: {question.name}")
        self.query_one("#help", Static).update(question.help.strip())
        authorize = self.query_one("#authorize", Static)
        command = question.authorize_command
        if command:
            authorize.update(
                "Run this on a computer with a browser, then paste the result below:\n" + command
            )
            authorize.display = True
        else:
            authorize.display = False
        choices = self.query_one("#choices", RadioSet)
        answer = self.query_one("#answer", Input)
        answer.password = question.is_password
        answer.value = ""
        if question.examples and question.exclusive:
            choices.remove_children()
            for example in question.examples:
                label = example["value"] + (f"  {example['help']}" if example["help"] else "")
                choices.mount(RadioButton(label, name=example["value"]))
            choices.display = True
            answer.display = False
        else:
            choices.display = False
            answer.display = True
            if question.examples:
                hint = ", ".join(e["value"] for e in question.examples[:6])
                answer.placeholder = f"examples: {hint}"
            else:
                answer.placeholder = (
                    "" if question.default is None else f"default: {question.default}"
                )
            answer.focus()

    def finish(self) -> None:
        try:
            dirs = self.service.list_dirs(self.remote_name)
        except RcloneError as error:
            self.show_error(f"remote created but listing failed: {error}")
            dirs = []
        self.dismiss({"created": True, "dirs": dirs})

    # -- buttons ---------------------------------------------------------------
    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#default")
    def _default(self) -> None:
        self.advance(None)

    @on(Button.Pressed, "#submit")
    @on(Input.Submitted, "#answer")
    def _submit(self) -> None:
        if self.question is None:
            return
        choices = self.query_one("#choices", RadioSet)
        if choices.display:
            pressed = choices.pressed_button
            if pressed is None:
                self.show_error("pick one of the options")
                return
            self.advance(pressed.name or "")
            return
        value = self.query_one("#answer", Input).value
        if self.question.required and not value and self.question.default in (None, ""):
            self.show_error("this option is required")
            return
        self.advance(value)
