"""Background execution of ``sb`` jobs for the daemon.

One job at a time, in a thread, so a request returns at once with the job
record and clients follow the log through the stream endpoint. The runner's
lock file still guards against a job started elsewhere (the TUI, ``sbx``).
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from typing import Any

from ..runner import Job, JobRunning, SbRunner


class JobManager:
    def __init__(self, runner: SbRunner):
        self.runner = runner
        self._thread: threading.Thread | None = None
        self._current: Job | None = None
        self._guard = threading.Lock()

    @property
    def current(self) -> Job | None:
        """The job this daemon is executing, or ``None``."""
        with self._guard:
            if self._current and self._thread and self._thread.is_alive():
                return self._current
            return None

    @property
    def busy(self) -> bool:
        return self.current is not None

    def start(
        self,
        kind: str,
        *,
        tags: Iterable[str] = (),
        skip_tags: Iterable[str] = (),
        extra_vars: Iterable[str] = (),
        verbosity: int = 0,
        no_cache: bool = False,
        verbose: bool = False,
    ) -> Job:
        """Prepare and start a job. Raises ``JobRunning`` when one is active."""
        tag_list = [t for t in tags if t]
        if kind == "install":
            command = self.runner.install_command(
                tag_list,
                skip_tags=skip_tags,
                extra_vars=extra_vars,
                verbosity=verbosity,
                no_cache=no_cache,
            )
        elif kind == "update":
            command = self.runner.update_command(verbose=verbose)
        elif kind == "validate":
            command = self.runner.validate_command()
        else:
            raise ValueError(f"unknown job kind: {kind}")
        with self._guard:
            if self._current and self._thread and self._thread.is_alive():
                raise JobRunning("a job is already running")
            if self.runner.is_locked() is not None:
                raise JobRunning("another Saltbox job is already running outside the daemon")
            job = self.runner.prepare(command, kind=kind, tags=tag_list)
            self._current = job
            self._thread = threading.Thread(
                target=self._execute, args=(job,), name=f"job-{job.id}", daemon=True
            )
            self._thread.start()
        return job

    def _execute(self, job: Job) -> None:
        try:
            self.runner.execute(job)
        except JobRunning:
            job.status, job.returncode = "failed", 1
            self.runner._save(job)
        except Exception as error:  # pragma: no cover - defensive, keeps the thread quiet
            job.status, job.returncode = "failed", 1
            self.runner._save(job)
            with open(job.log_path or "/dev/null", "a", encoding="utf-8") as log:
                log.write(f"daemon error: {error}\n")

    def cancel(self, job_id: str) -> bool:
        current = self.current
        if current is None or current.id != job_id:
            return False
        return self.runner.cancel()

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def status(self) -> dict[str, Any]:
        current = self.current
        return {
            "busy": current is not None,
            "current": current.as_dict() if current else None,
            "lock": self.runner.is_locked(),
        }
