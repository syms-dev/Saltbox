"""Rclone remotes through rclone's own non-interactive config API.

``rclone config create NAME TYPE --non-interactive`` prints the next question
as JSON. Posting the answer back with ``--continue --state S --result R``
yields the following question, until rclone has everything it needs. This
service wraps that loop so a UI can render any backend's questions without
hand-written forms, and handles the headless OAuth case the Saltbox docs
describe: say no to a local browser, show the ``rclone authorize`` command
for the user's own machine, paste the token back.

Every command runs as the Saltbox user so ``rclone.conf`` ends up in that
user's home with the right owner, the way the install expects.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

AUTHORIZE_RE = re.compile(r"(rclone authorize\s+\"[^\"]+\"(?:\s+\"[^\"]+\")*)")
AUTO_ANSWERS = {"config_is_local": "false"}

Runner = Callable[[list[str]], tuple[int, str, str]]


class RcloneError(RuntimeError):
    pass


@dataclass
class Question:
    """One option rclone asks for, from the ``Option`` object in its JSON."""

    state: str
    name: str
    help: str = ""
    default: Any = None
    examples: list[dict[str, str]] = field(default_factory=list)
    required: bool = False
    is_password: bool = False
    type: str = "string"
    exclusive: bool = False
    error: str = ""

    @property
    def authorize_command(self) -> str | None:
        match = AUTHORIZE_RE.search(self.help or "")
        return match.group(1) if match else None

    @property
    def is_token(self) -> bool:
        return self.name == "config_token"

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "name": self.name,
            "help": self.help,
            "default": self.default,
            "examples": self.examples,
            "required": self.required,
            "is_password": self.is_password,
            "type": self.type,
            "exclusive": self.exclusive,
            "error": self.error,
            "authorize_command": self.authorize_command,
        }


@dataclass
class Provider:
    name: str
    description: str
    options: list[dict[str, Any]]


class RcloneService:
    def __init__(
        self,
        binary: Path | str = "/usr/bin/rclone",
        *,
        user: str | None = None,
        config_path: Path | None = None,
        runner: Runner | None = None,
    ):
        self.binary = str(binary)
        self.user = user
        self.config_path = config_path or (
            Path(f"/home/{user}/.config/rclone/rclone.conf") if user else None
        )
        self._runner = runner or self._subprocess

    # -- plumbing ------------------------------------------------------------
    def command(self, *args: str) -> list[str]:
        base: list[str] = []
        if self.user:
            base = ["sudo", "-u", self.user, "-H"]
        cmd = [*base, self.binary]
        if self.config_path:
            cmd += ["--config", str(self.config_path)]
        return cmd + list(args)

    @staticmethod
    def _subprocess(cmd: list[str]) -> tuple[int, str, str]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
        except FileNotFoundError as error:
            raise RcloneError(f"rclone not found: {error}") from error
        except subprocess.TimeoutExpired as error:
            raise RcloneError(f"rclone timed out: {shlex.join(cmd)}") from error
        return result.returncode, result.stdout, result.stderr

    def run(self, *args: str) -> str:
        code, out, err = self._runner(self.command(*args))
        if code != 0:
            raise RcloneError((err or out or f"rclone exited {code}").strip())
        return out

    def run_json(self, *args: str) -> Any:
        out = self.run(*args)
        try:
            return json.loads(out) if out.strip() else None
        except ValueError as error:
            raise RcloneError(f"rclone returned invalid JSON: {out[:200]}") from error

    def available(self) -> bool:
        try:
            self.run("version")
        except RcloneError:
            return False
        return True

    # -- remotes ----------------------------------------------------------------
    def remotes(self) -> list[str]:
        out = self.run("listremotes")
        return [line.strip().rstrip(":") for line in out.splitlines() if line.strip()]

    def remote_types(self) -> dict[str, str]:
        data = self.run_json("config", "dump") or {}
        return {name: str(values.get("type", "")) for name, values in data.items()}

    def delete_remote(self, name: str) -> None:
        self.run("config", "delete", name)

    def providers(self) -> list[Provider]:
        data = self.run_json("config", "providers") or []
        return [
            Provider(p.get("Name", ""), p.get("Description", ""), p.get("Options") or [])
            for p in data
        ]

    def list_dirs(self, remote: str, path: str = "") -> list[str]:
        target = f"{remote}:{path}"
        data = self.run_json("lsjson", "--dirs-only", "--max-depth", "1", target) or []
        return sorted(entry.get("Name", "") for entry in data if entry.get("IsDir"))

    def mkdir(self, remote: str, path: str) -> None:
        self.run("mkdir", f"{remote}:{path}")

    def ensure_media_layout(self, remote: str, base: str = "Media") -> list[str]:
        """Create the folder layout Saltbox expects and return what was created."""
        created = []
        for folder in ("Movies", "TV", "Music"):
            path = f"{base}/{folder}"
            self.mkdir(remote, path)
            created.append(path)
        return created

    # -- non-interactive config ---------------------------------------------
    def create_step(
        self,
        name: str,
        remote_type: str,
        *,
        state: str = "",
        result: str | None = None,
        options: dict[str, str] | None = None,
        all_options: bool = False,
    ) -> Question | None:
        """Advance the config state machine by one question.

        Returns the next ``Question`` or ``None`` when the remote is complete.
        ``options`` are preset values passed as ``key=value`` on the first call.
        """
        args = ["config", "create", name, remote_type, "--non-interactive"]
        if all_options:
            args.append("--all")
        if state:
            args += ["--continue", "--state", state, "--result", "" if result is None else result]
        elif options:
            args += [f"{k}={v}" for k, v in options.items()]
        data = self.run_json(*args)
        return parse_question(data)

    def answer_loop(
        self,
        name: str,
        remote_type: str,
        ask: Callable[[Question], str | None],
        *,
        options: dict[str, str] | None = None,
        all_options: bool = False,
    ) -> None:
        """Run the question loop, calling ``ask`` for anything not auto-answered.

        ``ask`` returning ``None`` accepts rclone's default.
        """
        question = self.create_step(name, remote_type, options=options, all_options=all_options)
        while question is not None:
            if question.error:
                raise RcloneError(question.error)
            if question.name in AUTO_ANSWERS:
                answer: str | None = AUTO_ANSWERS[question.name]
            else:
                answer = ask(question)
            if answer is None:
                answer = "" if question.default is None else _as_text(question.default)
            question = self.create_step(name, remote_type, state=question.state, result=answer)


def parse_question(data: Any) -> Question | None:
    if not isinstance(data, dict):
        return None
    error = str(data.get("Error") or "")
    option = data.get("Option")
    if not option:
        if error:
            raise RcloneError(error)
        return None
    return Question(
        state=str(data.get("State") or ""),
        name=str(option.get("Name") or ""),
        help=str(option.get("Help") or ""),
        default=option.get("Default"),
        examples=[
            {"value": _as_text(e.get("Value")), "help": str(e.get("Help") or "")}
            for e in option.get("Examples") or []
        ],
        required=bool(option.get("Required")),
        is_password=bool(option.get("IsPassword")),
        type=str(option.get("Type") or "string"),
        exclusive=bool(option.get("Exclusive")),
        error=error,
    )


def _as_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)
