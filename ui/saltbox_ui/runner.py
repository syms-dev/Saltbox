"""Run ``sb`` and stream its output.

The engine never calls ``ansible-playbook`` itself. Every run is an ``sb``
invocation so tag validation, venv handling and sb's own checks apply.
One job runs at a time, guarded by a lock file, and every job writes a log
plus a small JSON record so a UI can show history after the process that
started the job is gone.
"""

from __future__ import annotations

import codecs
import contextlib
import fcntl
import json
import os
import pty
import pwd
import select
import shlex
import signal
import struct
import subprocess
import sys
import termios
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .layout import Layout

LineCallback = Callable[[str], None]

# Started in place of a command that must own a terminal: it makes the
# pseudo-terminal on its stdin the controlling terminal of a new session, then
# becomes the command (same process id), as a login shell's terminal would be.
# A helper process rather than ``preexec_fn``, which can deadlock a threaded
# parent.
_TERMINAL_EXEC = """
import fcntl, os, sys, termios
try:
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
except OSError:
    pass
try:
    os.execvp(sys.argv[1], sys.argv[1:])
except OSError as error:
    print(f"failed to start: {error}")
    sys.exit(127)
"""
TERMINAL_SIZE = (40, 120)  # rows, columns
MAX_RUNS = 3


class Terminal(Protocol):
    """The far end of a pseudo-terminal: reads what the command prints, types what it needs."""

    rerun: bool
    error: str | None

    def feed(self, text: str) -> list[str]: ...
    def flush(self) -> list[str]: ...
    def keys(self) -> bytes: ...
    def record(self) -> dict[str, Any]: ...
    def restart(self) -> None: ...


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
    # Set while the command waits for an answer only a person should give.
    question: dict[str, Any] | None = None
    # Announcements the command showed (``sb update``).
    announcements: list[dict[str, Any]] = field(default_factory=list)

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


def ensure_home(env: dict[str, str]) -> dict[str, str]:
    """Give ``env`` a ``HOME`` when it has none.

    systemd starts services without ``HOME``. Saltbox's first task runs
    ``git config --global``, which fails with "$HOME not set" without it.
    """
    if not env.get("HOME"):
        try:
            env["HOME"] = pwd.getpwuid(os.geteuid()).pw_dir or "/root"
        except KeyError:
            env["HOME"] = "/root"
    return env


def trust_repos(env: dict[str, str], repos: Iterable[Path]) -> dict[str, str]:
    """Mark ``repos`` as safe for git in ``env``, keeping any config entries already there.

    The daemon runs as root from systemd while the checkouts belong to the
    Saltbox user. ``sudo sb`` gets away with that because git honours
    ``SUDO_UID``; without it git refuses the repository ("dubious
    ownership") and sb fails before Ansible starts. ``GIT_CONFIG_*`` entries
    count as command-line config, which is where git accepts
    ``safe.directory``, and they reach every git that sb and Ansible start.
    """
    try:
        count = int(env.get("GIT_CONFIG_COUNT", "0"))
    except ValueError:
        count = 0
    present = {
        env.get(f"GIT_CONFIG_VALUE_{i}")
        for i in range(count)
        if env.get(f"GIT_CONFIG_KEY_{i}") == "safe.directory"
    }
    for repo in repos:
        if str(repo) in present:
            continue
        env[f"GIT_CONFIG_KEY_{count}"] = "safe.directory"
        env[f"GIT_CONFIG_VALUE_{count}"] = str(repo)
        present.add(str(repo))
        count += 1
    env["GIT_CONFIG_COUNT"] = str(count)
    return env


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
        self._process: subprocess.Popen[Any] | None = None
        self._cancelled = False

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

    def update_command(self) -> list[str]:
        """``sb update`` as this engine runs it, on a pseudo-terminal (see ``sbupdate``).

        ``--verbose`` makes sb print plain lines instead of drawing spinners.
        ``--keep-branch`` answers the question sb asks when a checkout is not on
        its default branch the way sb itself does without a terminal: stay.
        """
        return [str(self.sb), "update", "--verbose", "--keep-branch"]

    def validate_command(self) -> list[str]:
        return [str(self.sb), "validate-config"]

    def list_command(self, query: str | None = None) -> list[str]:
        command = [str(self.sb), "list"]
        if query:
            command.append(query)
        return command

    # -- job persistence ---------------------------------------------------
    @staticmethod
    def _private_dir(path: Path) -> None:
        """Create ``path`` readable by its owner only: Ansible logs can hold secrets."""
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.stat().st_mode & 0o077:
            path.chmod(0o700)  # tighten a directory an older version created

    def _save(self, job: Job) -> None:
        """Persist the record atomically so a concurrent reader never sees a partial file."""
        self._private_dir(self.jobs_dir)
        path = self.jobs_dir / f"{job.id}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(job.as_dict(), indent=1), encoding="utf-8")
        tmp.replace(path)

    def jobs(self, limit: int = 50) -> list[Job]:
        if not self.jobs_dir.exists():
            return []
        records = sorted(
            (p for p in self.jobs_dir.glob("*.json") if not p.name.endswith(".tmp")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
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
    def prepare(
        self, command: list[str], *, kind: str = "command", tags: Iterable[str] = ()
    ) -> Job:
        """Create and persist a pending job without starting it."""
        job = Job(id=uuid.uuid4().hex[:12], command=list(command), kind=kind, tags=list(tags))
        self._private_dir(self.jobs_dir)
        job.log_path = str(self.jobs_dir / f"{job.id}.log")
        self._save(job)
        return job

    def run(
        self,
        command: list[str],
        *,
        kind: str = "command",
        tags: Iterable[str] = (),
        on_line: LineCallback | None = None,
        cwd: Path | None = None,
        terminal: Terminal | None = None,
    ) -> Job:
        """Run ``command`` to completion, streaming merged output line by line."""
        job = self.prepare(command, kind=kind, tags=tags)
        return self.execute(job, on_line=on_line, cwd=cwd, terminal=terminal)

    def execute(
        self,
        job: Job,
        *,
        on_line: LineCallback | None = None,
        cwd: Path | None = None,
        terminal: Terminal | None = None,
    ) -> Job:
        """Run a prepared job. Raises ``JobRunning`` when another job holds the lock.

        With ``terminal``, the command runs on a pseudo-terminal and that object
        reads its output and types its input; otherwise its output is a pipe.
        """
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        log_path = Path(job.log_path or self.jobs_dir / f"{job.id}.log")
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
            ensure_home(env)
            trust_repos(
                env,
                (self.layout.repo, self.layout.sandbox_repo, self.layout.saltbox_mod_repo),
            )
            log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with open(log_fd, "w", encoding="utf-8") as log:
                log.write(f"$ {job.command_line}\n")

                def emit(line: str) -> None:
                    log.write(line + "\n")
                    log.flush()
                    if on_line:
                        on_line(line)

                self._cancelled = False
                workdir = str(cwd or self.layout.repo)
                try:
                    if terminal is None:
                        returncode = self._run_piped(job.command, env, workdir, emit)
                    else:
                        returncode = self._run_on_terminal(job, env, workdir, emit, terminal)
                except OSError as error:
                    emit(f"failed to start: {error}")
                    job.status, job.returncode, job.finished_at = "failed", 127, _now()
                    self._save(job)
                    return job
                except KeyboardInterrupt:
                    job.status, job.returncode, job.finished_at = "interrupted", 130, _now()
                    job.question = None
                    self._save(job)
                    raise
                if self._cancelled:
                    log.write("cancelled\n")
            if self._cancelled:
                job.status, job.returncode = "interrupted", returncode
            else:
                job.returncode = returncode
                job.status = "succeeded" if returncode == 0 else "failed"
            job.question = None
            job.finished_at = _now()
            self._save(job)
            fcntl.flock(lock, fcntl.LOCK_UN)
        return job

    def _run_piped(
        self, command: list[str], env: dict[str, str], cwd: str, emit: LineCallback
    ) -> int:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            env=env,
            text=True,
            errors="replace",
            bufsize=1,
            # Its own process group, so cancelling stops ansible-playbook and
            # everything else sb started, not only sb.
            start_new_session=True,
        )
        assert process.stdout is not None
        self._process = process
        try:
            for line in process.stdout:
                emit(line.rstrip("\n"))
            return process.wait()
        except KeyboardInterrupt:
            self._stop(process)
            raise
        finally:
            self._process = None

    def _run_on_terminal(
        self, job: Job, env: dict[str, str], cwd: str, emit: LineCallback, terminal: Terminal
    ) -> int:
        """Run the job's command on a pseudo-terminal, again if it asks to be re-run."""
        returncode = 1
        for attempt in range(MAX_RUNS):
            if attempt:
                terminal.restart()
                emit("sb updated itself; running the update again")
            returncode = self._terminal_session(job, env, cwd, emit, terminal)
            if returncode != 0 or not terminal.rerun or self._cancelled:
                break
        return returncode

    def _terminal_session(
        self, job: Job, env: dict[str, str], cwd: str, emit: LineCallback, terminal: Terminal
    ) -> int:
        master, slave = pty.openpty()
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", *TERMINAL_SIZE, 0, 0))
            process = subprocess.Popen(
                [sys.executable, "-I", "-c", _TERMINAL_EXEC, *job.command],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=cwd,
                env=env,
            )
        except OSError:
            os.close(master)
            raise
        finally:
            os.close(slave)
        self._process = process
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

        def sync() -> None:
            record = terminal.record()
            if any(getattr(job, key) != value for key, value in record.items()):
                for key, value in record.items():
                    setattr(job, key, value)
                self._save(job)

        try:
            while True:
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try:
                        data = os.read(master, 65536)
                    except OSError:  # EIO: nothing holds the terminal open any more
                        data = b""
                    if not data:
                        break
                    for line in terminal.feed(decoder.decode(data)):
                        emit(line)
                elif process.poll() is not None:
                    break  # the command is gone; do not wait on anything it left behind
                keys = terminal.keys()
                if keys:
                    with contextlib.suppress(OSError):  # the command may already be gone
                        os.write(master, keys)
                sync()
                if terminal.error:
                    emit(terminal.error)
                    self._stop(process)
                    return 1
            for line in terminal.flush():
                emit(line)
            sync()
            return process.wait()
        except KeyboardInterrupt:
            self._stop(process)
            raise
        finally:
            self._process = None
            os.close(master)

    @staticmethod
    def _stop(process: subprocess.Popen[Any]) -> None:
        """Stop the job's whole process group: SIGTERM, then SIGKILL after 10 seconds.

        Signalling only ``sb`` leaves its children running with the log pipe
        open, so the job would carry on and never finish.
        """

        def signal_group(sig: signal.Signals) -> None:
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
            except PermissionError:
                process.send_signal(sig)

        signal_group(signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            signal_group(signal.SIGKILL)
            process.wait()
        else:
            signal_group(signal.SIGKILL)  # anything sb left behind in the group

    def cancel(self) -> bool:
        """Stop the job this runner is executing, if any. Returns whether one was stopped."""
        process = self._process
        if process is None or process.poll() is not None:
            return False
        self._cancelled = True
        self._stop(process)
        return True

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

    def update(
        self, *, on_line: LineCallback | None = None, terminal: Terminal | None = None
    ) -> Job:
        """``sb update``. It needs a terminal: pass one, or one is made that declines questions."""
        from .sbupdate import UpdateTerminal

        if terminal is None:
            terminal = UpdateTerminal.for_layout(self.layout, ask=lambda question: False)
        return self.run(self.update_command(), kind="update", on_line=on_line, terminal=terminal)

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
