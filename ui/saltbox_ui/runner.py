"""Run ``sb`` and stream its output.

The engine never calls ``ansible-playbook`` itself. Every run is an ``sb``
invocation so tag validation, venv handling and sb's own checks apply.
One job runs at a time, guarded by a lock file, and every job writes a log
plus a small JSON record so a UI can show history after the process that
started the job is gone.
"""

from __future__ import annotations

import fcntl
import json
import os
import shlex
import subprocess
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .layout import Layout

LineCallback = Callable[[str], None]


class JobRunning(RuntimeError):
    """Another job holds the runner lock."""


@dataclass
class Job:
    id: str
    command: list[str]
    kind: str
    status: str = "pending"  # pending, running, succeeded, failed, interrupted
    returncode: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    log_path: str | None = None
    tags: list[str] = field(default_factory=list)

    @property
    def command_line(self) -> str:
        return shlex.join(self.command)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["command_line"] = self.command_line
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SbRunner:
    def __init__(
        self, layout: Layout, *, sb: Path | None = None, env: dict[str, str] | None = None
    ):
        self.layout = layout
        self.sb = Path(sb) if sb is not None else layout.sb_binary
        self.env = env
        self.jobs_dir = layout.jobs_dir
        self.lock_file = layout.lock_file

    # -- command builders --------------------------------------------------
    def install_command(
        self,
        tags: Iterable[str],
        *,
        skip_tags: Iterable[str] = (),
        extra_vars: Iterable[str] = (),
        verbosity: int = 0,
        no_cache: bool = False,
    ) -> list[str]:
        tag_list = [t.strip() for t in tags if t and t.strip()]
        if not tag_list:
            raise ValueError("at least one tag is required")
        command = [str(self.sb), "install", ",".join(tag_list)]
        skip = [t.strip() for t in skip_tags if t and t.strip()]
        if skip:
            command += ["--skip-tags", ",".join(skip)]
        for var in extra_vars:
            command += ["--extra-vars", var]
        if verbosity > 0:
            command.append("-" + "v" * min(verbosity, 4))
        if no_cache:
            command.append("--no-cache")
        return command

    def update_command(self, *, verbose: bool = False) -> list[str]:
        command = [str(self.sb), "update"]
        if verbose:
            command.append("--verbose")
        return command

    def validate_command(self) -> list[str]:
        return [str(self.sb), "validate-config"]

    def list_command(self, query: str | None = None) -> list[str]:
        command = [str(self.sb), "list"]
        if query:
            command.append(query)
        return command

    # -- job persistence ---------------------------------------------------
    def _save(self, job: Job) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        (self.jobs_dir / f"{job.id}.json").write_text(
            json.dumps(job.as_dict(), indent=1), encoding="utf-8"
        )

    def jobs(self, limit: int = 50) -> list[Job]:
        if not self.jobs_dir.exists():
            return []
        records = sorted(
            self.jobs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        result = []
        for path in records[:limit]:
            try:
                result.append(Job.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (ValueError, TypeError):
                continue
        return result

    def job(self, job_id: str) -> Job | None:
        path = self.jobs_dir / f"{job_id}.json"
        if not path.exists():
            return None
        return Job.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def log(self, job_id: str) -> str:
        path = self.jobs_dir / f"{job_id}.log"
        return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""

    # -- execution ---------------------------------------------------------
    def run(
        self,
        command: list[str],
        *,
        kind: str = "command",
        tags: Iterable[str] = (),
        on_line: LineCallback | None = None,
        cwd: Path | None = None,
    ) -> Job:
        """Run ``command`` to completion, streaming merged output line by line."""
        job = Job(id=uuid.uuid4().hex[:12], command=list(command), kind=kind, tags=list(tags))
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        log_path = self.jobs_dir / f"{job.id}.log"
        job.log_path = str(log_path)
        with open(self.lock_file, "a+", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise JobRunning("another Saltbox job is already running") from error
            lock.seek(0)
            lock.truncate()
            lock.write(json.dumps({"job": job.id, "pid": os.getpid(), "started": time.time()}))
            lock.flush()
            job.status, job.started_at = "running", _now()
            self._save(job)
            env = dict(os.environ if self.env is None else self.env)
            env.setdefault("TERM", "dumb")
            env.setdefault("ANSIBLE_FORCE_COLOR", "0")
            env.setdefault("NO_COLOR", "1")
            with open(log_path, "w", encoding="utf-8") as log:
                log.write(f"$ {job.command_line}\n")
                try:
                    process = subprocess.Popen(
                        job.command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        cwd=str(cwd or self.layout.repo),
                        env=env,
                        text=True,
                        errors="replace",
                        bufsize=1,
                    )
                except OSError as error:
                    message = f"failed to start: {error}"
                    log.write(message + "\n")
                    if on_line:
                        on_line(message)
                    job.status, job.returncode, job.finished_at = "failed", 127, _now()
                    self._save(job)
                    return job
                assert process.stdout is not None
                try:
                    for line in process.stdout:
                        log.write(line)
                        log.flush()
                        if on_line:
                            on_line(line.rstrip("\n"))
                    returncode = process.wait()
                except KeyboardInterrupt:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    job.status, job.returncode, job.finished_at = "interrupted", 130, _now()
                    self._save(job)
                    raise
            job.returncode = returncode
            job.status = "succeeded" if returncode == 0 else "failed"
            job.finished_at = _now()
            self._save(job)
            fcntl.flock(lock, fcntl.LOCK_UN)
        return job

    def install(
        self, tags: Iterable[str], *, on_line: LineCallback | None = None, **options: Any
    ) -> Job:
        tag_list = list(tags)
        return self.run(
            self.install_command(tag_list, **options),
            kind="install",
            tags=tag_list,
            on_line=on_line,
        )

    def update(self, *, on_line: LineCallback | None = None, verbose: bool = False) -> Job:
        return self.run(self.update_command(verbose=verbose), kind="update", on_line=on_line)

    def is_locked(self) -> dict[str, Any] | None:
        """Return the lock holder's record when a job is running, else ``None``."""
        if not self.lock_file.exists():
            return None
        with open(self.lock_file, encoding="utf-8") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                try:
                    return json.loads(lock.read() or "{}")
                except ValueError:
                    return {}
            fcntl.flock(lock, fcntl.LOCK_UN)
        return None
