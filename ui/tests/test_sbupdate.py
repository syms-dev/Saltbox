"""``sb update`` on a pseudo-terminal: the daemon reads the screen and types for it."""

import json
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saltbox_ui.daemon import Services, create_app
from saltbox_ui.layout import Layout
from saltbox_ui.runner import SbRunner
from saltbox_ui.sbupdate import (
    ALT_SCREEN_OFF,
    ALT_SCREEN_ON,
    UpdateTerminal,
    clean_line,
    new_announcements,
)

FAKE = Path(__file__).parent / "fake_sb_update.py"
MIGRATION = {"repo": "Saltbox", "tag": "e2e-migration", "date": "2031-01-01"}
EXISTING = 'announcements:\n  - date: "2026-02-01"\n    title: Old news\n    message: old\n'
TABLE = (
    "\r\nThe following tags need to be run to handle migrations:\r\n\r\n"
    "  #  Repo      Tag             Announcement Date\r\n"
    "  -  -------   -------------   -----------------\r\n"
    "  1  Saltbox   e2e-migration   2031-01-01\r\n"
    "\r\nRun all migration tags? (y/n): "
)


@pytest.fixture
def update_sb(tmp_path: Path) -> Path:
    """An ``sb`` whose ``update`` behaves at the terminal like the real one."""
    path = tmp_path / "bin" / "sb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\nexec {sys.executable} {FAKE} "$@"\n')
    path.chmod(0o755)
    return path


def wait_for(condition, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("timed out")


def start(runner: SbRunner, terminal: UpdateTerminal) -> tuple[threading.Thread, list]:
    done: list = []
    thread = threading.Thread(
        target=lambda: done.append(
            runner.run(runner.update_command(), kind="update", terminal=terminal)
        ),
        daemon=True,
    )
    thread.start()
    return thread, done


def current(runner: SbRunner):
    jobs = runner.jobs(limit=1)
    return jobs[0] if jobs else None


# -- reading the screen ------------------------------------------------------------------
def test_clean_line_removes_escapes_and_keeps_the_last_rewrite() -> None:
    assert clean_line("\x1b[94mSaltbox updated\x1b[0m\r") == "Saltbox updated"
    assert clean_line("Receiving:  50%\rReceiving: 100%, done.\r") == "Receiving: 100%, done."
    assert clean_line("\x1b]0;title\x07plain\x1b[?25h") == "plain"


def test_new_announcements_follow_sbs_rules(tmp_path: Path) -> None:
    folder = tmp_path / "plex"
    folder.mkdir()
    old = {"date": "2026-01-01", "title": "Old", "message": "old"}
    after = [
        old,
        {"date": "2026-03-01", "title": "Later", "message": "later\n"},
        {
            "date": "2026-02-01",
            "title": "Earlier",
            "message": "earlier",
            "migration": {"required": True, "tag": "move-things"},
            "required_folder": str(folder),
        },
        {"date": "2026-02-02", "title": "Not here", "required_folder": str(tmp_path / "none")},
        {"date": "2026-02-03", "title": "Optional", "migration": {"required": False, "tag": "x"}},
    ]
    found = new_announcements("Saltbox", [old], after)
    assert [a["title"] for a in found] == ["Earlier", "Optional", "Later"]  # oldest first
    assert found[0]["migration"] == "move-things" and found[1]["migration"] is None
    assert found[2]["message"] == "later"
    # No file before the update: everything in it is new. No file after: nothing is.
    assert len(new_announcements("Saltbox", None, after)) == 4
    assert new_announcements("Saltbox", [old], None) == []


def repo_with_announcement(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "announcements.yml").write_text(EXISTING)
    return repo


def test_terminal_closes_the_viewer_and_logs_what_it_showed(tmp_path: Path) -> None:
    repo = repo_with_announcement(tmp_path)
    terminal = UpdateTerminal({"Saltbox": repo})
    assert terminal.feed("\x1b[94mDisplaying new announcements\x1b[0m\r\n") == [
        "Displaying new announcements"
    ]
    assert terminal.keys() == b""
    (repo / "announcements.yml").write_text(
        EXISTING + '  - date: "2031-01-01"\n    title: Moved\n    message: |\n'
        "      ## Heading\n\n      Body text.\n"
    )
    # The sequence that opens the viewer arrives split across two reads.
    assert terminal.feed(ALT_SCREEN_ON[:4]) == []
    lines = terminal.feed(ALT_SCREEN_ON[4:] + "\x1b[2J# Saltbox Announcement  q: Quit")
    assert lines == [
        "",
        "== Saltbox announcement, 2031-01-01: Moved ==",
        "## Heading",
        "",
        "Body text.",
        "",
    ]
    assert terminal.keys() == b"q"
    assert terminal.keys() == b""  # not again straight away
    assert terminal.record()["announcements"][0]["title"] == "Moved"
    # What the viewer draws is not log output; what follows it is.
    assert terminal.feed("redraw redraw" + ALT_SCREEN_OFF[:5]) == []
    assert terminal.feed(ALT_SCREEN_OFF[5:] + "Validating\r\n") == ["Validating"]
    assert terminal.keys() == b""


def test_terminal_gives_up_on_a_viewer_that_never_closes(tmp_path: Path) -> None:
    now = [0.0]
    terminal = UpdateTerminal({"Saltbox": repo_with_announcement(tmp_path)}, clock=lambda: now[0])
    terminal.feed(ALT_SCREEN_ON)
    assert terminal.keys() == b"q"
    now[0] = 1.5
    assert terminal.keys() == b"q"  # asked again after a second
    now[0] = 61.0
    terminal.keys()
    assert terminal.error == "sb's announcement viewer did not close"


def test_terminal_raises_the_migration_question_and_types_the_answer(tmp_path: Path) -> None:
    terminal = UpdateTerminal({"Saltbox": repo_with_announcement(tmp_path)})
    assert terminal.answer(True) is False  # nothing asked yet
    terminal.feed(TABLE[:60])
    assert terminal.question is None
    terminal.feed(TABLE[60:])
    assert terminal.question == {
        "kind": "migrations",
        "migrations": [MIGRATION],
        "text": "\n".join(TABLE.replace("\r", "").split("\n")[3:6]),
    }
    assert terminal.keys() == b""  # it waits for a person
    assert terminal.answer(False) is True
    assert terminal.question is None and terminal.keys() == b"n\n"
    assert terminal.answer(False) is False
    # The terminal echoes what was typed, which finishes the prompt's line.
    assert terminal.feed("n\r\n") == ["Run all migration tags? (y/n): n"]
    assert terminal.question is None


def test_terminal_repeats_an_answer_sb_misread(tmp_path: Path) -> None:
    terminal = UpdateTerminal({"Saltbox": repo_with_announcement(tmp_path)})
    terminal.feed(TABLE)
    terminal.answer(True)
    assert terminal.keys() == b"y\n"
    # A key left over from the viewer got in front of the answer.
    terminal.feed("qy\r\nInvalid input. Please enter 'y' (yes) or 'n' (no).\r\n")
    terminal.feed("\r\nRun all migration tags? (y/n): ")
    assert terminal.question is None  # the person is not asked twice
    assert terminal.keys() == b"y\n"


def test_command_line_answers_at_once(tmp_path: Path) -> None:
    asked: list = []
    terminal = UpdateTerminal(
        {"Saltbox": repo_with_announcement(tmp_path)}, ask=lambda q: asked.append(q) or True
    )
    terminal.feed(TABLE)
    assert asked[0]["migrations"] == [MIGRATION]
    assert terminal.question is None and terminal.keys() == b"y\n"


# -- the real thing: a process on a pseudo-terminal --------------------------------------------
def test_sb_update_refuses_a_pipe_which_is_why_it_gets_a_terminal(
    scratch_layout: Layout, update_sb: Path
) -> None:
    runner = SbRunner(scratch_layout, sb=update_sb)
    job = runner.run(runner.update_command(), kind="update")
    assert job.status == "failed"
    assert "requires an interactive terminal" in runner.log(job.id)


@pytest.mark.parametrize("yes", [True, False])
def test_update_shows_announcements_and_waits_for_the_migration_answer(
    scratch_layout: Layout, update_sb: Path, yes: bool
) -> None:
    announcements = scratch_layout.repo / "announcements.yml"
    announcements.write_text(EXISTING)
    runner = SbRunner(scratch_layout, sb=update_sb)
    terminal = UpdateTerminal.for_layout(scratch_layout)
    thread, done = start(runner, terminal)
    try:
        waiting = wait_for(lambda: (job := current(runner)) and job.question and job)
        assert waiting.status == "running"
        assert waiting.question["migrations"] == [MIGRATION]
        assert [a["title"] for a in waiting.announcements] == ["Test migration"]
        assert waiting.announcements[0]["migration"] == "e2e-migration"
        time.sleep(0.5)
        assert thread.is_alive(), "the update went on without an answer"
        assert terminal.answer(yes) is True
    finally:
        thread.join(timeout=15)
        runner.cancel()  # a failed assertion must not leave the update waiting
    job = done[0]
    assert job.status == "succeeded" and job.question is None
    assert runner.job(job.id).question is None
    assert [a["title"] for a in runner.job(job.id).announcements] == ["Test migration"]
    log = runner.log(job.id)
    assert "\x1b" not in log and "\r" not in log
    assert "Saltbox: Updating the current branch 'test'" in log
    assert "Receiving objects: 100% (2/2), done." in log and "50%" not in log
    assert "== Saltbox announcement, 2031-01-01: Test migration ==" in log
    assert "Something moved, and existing installs need a migration." in log
    assert "q: Quit" not in log  # the viewer's own drawing stays out of the log
    assert f"Run all migration tags? (y/n): {'y' if yes else 'n'}" in log
    assert ("Running migration 'e2e-migration'" in log) is yes
    assert log.rstrip().endswith("Validating Saltbox configuration")
    assert announcements.read_text() == EXISTING


def test_cancel_while_the_update_waits_for_an_answer(
    scratch_layout: Layout, update_sb: Path
) -> None:
    runner = SbRunner(scratch_layout, sb=update_sb)
    terminal = UpdateTerminal.for_layout(scratch_layout)
    thread, done = start(runner, terminal)
    try:
        wait_for(lambda: (job := current(runner)) and job.question)
    finally:
        cancelled = runner.cancel()
        thread.join(timeout=15)
    assert cancelled is True
    assert done[0].status == "interrupted" and done[0].question is None
    assert terminal.answer(True) is False
    assert not (scratch_layout.repo / "announcements.yml").exists()  # the fake cleaned up


def test_update_runs_again_after_sb_updates_itself(
    scratch_layout: Layout, update_sb: Path, tmp_path: Path
) -> None:
    import os

    marker = tmp_path / "self-updated"
    env = {**os.environ, "FAKE_SB_SELF_UPDATE": str(marker), "FAKE_SB_QUIET": "1"}
    runner = SbRunner(scratch_layout, sb=update_sb, env=env)
    job = runner.update()
    assert job.status == "succeeded" and marker.exists()
    lines = runner.log(job.id).splitlines()
    assert lines.index("Successfully updated sb CLI to version: 9.9.9") < lines.index(
        "sb updated itself; running the update again"
    )
    assert lines.index("sb updated itself; running the update again") < lines.index(
        "Saltbox updated"
    )
    assert lines.count("Saltbox updated") == 1


def test_update_without_a_person_declines_migrations(
    scratch_layout: Layout, update_sb: Path
) -> None:
    """``runner.update()`` with no terminal given (a script): migrations are not approved."""
    runner = SbRunner(scratch_layout, sb=update_sb)
    job = runner.update()
    log = runner.log(job.id)
    assert job.status == "succeeded"
    assert "Run all migration tags? (y/n): n" in log and "Running migration" not in log


# -- through the daemon ----------------------------------------------------------------------
def test_answering_through_the_api(scratch_layout: Layout, update_sb: Path) -> None:
    services = Services(scratch_layout)
    client = TestClient(create_app(services=services))
    job = client.post("/api/jobs", json={"kind": "update"}).json()
    assert job["command"][1:] == ["update", "--verbose", "--keep-branch"]
    path = f"/api/jobs/{job['id']}"

    def asked():
        record = client.get(path).json()
        return record if record.get("question") else None

    try:
        record = wait_for(asked)
    except AssertionError:
        services.jobs.cancel(job["id"])
        raise
    assert record["question"]["migrations"] == [MIGRATION]
    assert record["announcements"][0]["title"] == "Test migration"
    assert client.get("/api/jobs").json()["current"]["question"]["kind"] == "migrations"
    assert client.post(f"{path}/answer", json={"answer": "maybe"}).status_code == 422
    assert client.post("/api/jobs/nope/answer", json={"answer": True}).status_code == 404
    assert client.post(f"{path}/answer", json={"answer": True}).json() == {"answered": True}
    services.jobs.wait(15)
    finished = client.get(path).json()
    assert finished["status"] == "succeeded" and finished["question"] is None
    assert finished["announcements"][0]["title"] == "Test migration"
    assert "Running migration 'e2e-migration'" in client.get(f"{path}/log").json()["text"]
    late = client.post(f"{path}/answer", json={"answer": True})
    assert late.status_code == 409 and "not waiting" in late.json()["detail"]


# -- from the command line ------------------------------------------------------------------
def test_sbx_run_update_answers_as_told(env_layout: Layout, update_sb: Path, capsys) -> None:
    from saltbox_ui import cli

    assert cli.main(["run", "update", "--migrations", "yes"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "succeeded"
    assert "Running migration 'e2e-migration'" in captured.err
    # Left to ask, with no terminal to ask at, it does not approve and says so.
    assert cli.main(["run", "update"]) == 0
    captured = capsys.readouterr()
    assert "Saltbox: e2e-migration" in captured.err and "--migrations yes" in captured.err
    assert "Running migration" not in captured.err
