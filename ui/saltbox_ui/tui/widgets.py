"""Widgets shared by the installer and, later, the management screens."""

from __future__ import annotations

import contextlib
from collections.abc import Iterable
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Input, Label, SelectionList, Static

CHECK_GLYPHS = {"pass": "✓", "warn": "!", "fail": "✗", "skip": "-", "running": "…"}
CHECK_CLASSES = {"pass": "ok", "warn": "warn", "fail": "error", "skip": "hint", "running": "hint"}


class StepScreen(Screen):
    """One wizard step: header with step counter, a body, Back and Next buttons.

    Subclasses implement ``body()`` and ``commit()``. ``commit`` stores the
    answers into the plan and returns an error message to block, or ``None``.
    """

    TITLE = "Step"
    NEXT_LABEL = "Next"
    BACK_LABEL = "Back"
    SHOW_BACK = True
    SHOW_NEXT = True

    class Navigate(Message):
        def __init__(self, direction: int) -> None:
            super().__init__()
            self.direction = direction

    def __init__(self, index: int, total: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.index = index
        self.total = total

    def compose(self) -> ComposeResult:
        with Horizontal(id="step-header"):
            yield Static(f"Saltbox installer · {self.TITLE}", classes="title")
            yield Static(f"step {self.index + 1} of {self.total}", classes="counter")
        with VerticalScroll(id="body"):
            yield from self.body()
        with Horizontal(id="nav"):
            if self.SHOW_BACK:
                yield Button(self.BACK_LABEL, id="back")
            yield Static("", id="step-error", classes="spacer error")
            if self.SHOW_NEXT:
                yield Button(self.NEXT_LABEL, id="next", variant="primary")

    def body(self) -> ComposeResult:  # pragma: no cover - abstract
        yield from ()

    def commit(self) -> str | None:
        return None

    def set_next_enabled(self, enabled: bool) -> None:
        with contextlib.suppress(Exception):  # screen may not be composed yet
            self.query_one("#next", Button).disabled = not enabled

    @on(Button.Pressed, "#back")
    def _back(self) -> None:
        self.post_message(self.Navigate(-1))

    @on(Button.Pressed, "#next")
    def _next(self) -> None:
        error = self.commit()
        if error:
            self.notify_error(error)
            return
        self.notify_error("")
        self.post_message(self.Navigate(+1))

    def notify_error(self, message: str) -> None:
        """Show ``message`` in the nav bar. Toasts would cover the Next button."""
        self.query_one("#step-error", Static).update(message)


class FieldRow(Vertical):
    """A labelled input with an optional hint line."""

    DEFAULT_CSS = """
    FieldRow { height: auto; }
    """

    def __init__(self, label: str, widget: Input | Any, hint: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._widget = widget
        self._hint = hint

    def compose(self) -> ComposeResult:
        yield Label(self._label, classes="field-label")
        yield self._widget
        if self._hint:
            yield Static(self._hint, classes="hint")


class CheckRow(Horizontal):
    """One preflight result. ``update`` may be called before the row is composed."""

    def __init__(
        self,
        check_id: str,
        title: str,
        status: str = "running",
        detail: str = "",
        hint: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(classes="check-row", **kwargs)
        self.check_id = check_id
        self.title = title
        self.status = status
        self.detail = detail
        self.hint = hint

    def compose(self) -> ComposeResult:
        yield Static(self._glyph(), classes=f"glyph {self._class()}", id="glyph")
        yield Static(self.title, classes="check-title")
        yield Static(self._text(), classes="check-detail", id="detail")

    def _glyph(self) -> str:
        return CHECK_GLYPHS.get(self.status, "?")

    def _class(self) -> str:
        return CHECK_CLASSES.get(self.status, "hint")

    def _text(self) -> str:
        if self.hint:
            return f"{self.detail} · {self.hint}" if self.detail else self.hint
        return self.detail

    def update(self, status: str, detail: str = "", hint: str = "") -> None:
        self.status, self.detail, self.hint = status, detail, hint
        glyphs = self.query("#glyph")
        if not glyphs:
            return  # not composed yet; compose() renders the stored values
        glyph = glyphs.first(Static)
        glyph.update(self._glyph())
        glyph.set_classes(f"glyph {self._class()}")
        self.query_one("#detail", Static).update(self._text())


class FilterableSelection(Vertical):
    """A SelectionList with a filter box above it, keeping selections across filters."""

    DEFAULT_CSS = """
    FilterableSelection { height: auto; }
    FilterableSelection Input { width: 100%; }
    """

    def __init__(
        self,
        items: Iterable[tuple[str, str]],
        selected: Iterable[str] = (),
        *,
        placeholder: str = "Filter…",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.items = list(items)
        self.selected_values: set[str] = set(selected)
        self.placeholder = placeholder

    def compose(self) -> ComposeResult:
        yield Input(placeholder=self.placeholder, id="filter")
        yield SelectionList[str](*self._entries(""), id="list")

    def _entries(self, needle: str) -> list[tuple[str, str, bool]]:
        needle = needle.lower()
        return [
            (label, value, value in self.selected_values)
            for label, value in self.items
            if not needle or needle in label.lower() or needle in value.lower()
        ]

    @on(Input.Changed, "#filter")
    def _filter(self, event: Input.Changed) -> None:
        lst = self.query_one("#list", SelectionList)
        lst.clear_options()
        lst.add_options(self._entries(event.value))

    @on(SelectionList.SelectionToggled, "#list")
    def _toggled(self, event: SelectionList.SelectionToggled) -> None:
        value = event.selection.value
        if value in self.selected_values:
            self.selected_values.discard(value)
        else:
            self.selected_values.add(value)

    @property
    def selected(self) -> list[str]:
        order = [value for _, value in self.items]
        return [v for v in order if v in self.selected_values]
