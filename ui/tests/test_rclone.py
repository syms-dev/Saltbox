from __future__ import annotations

import json
from pathlib import Path

import pytest

from saltbox_ui.rclone import Question, RcloneError, RcloneService
from saltbox_ui.rclone.service import parse_question


@pytest.fixture
def service(fake_rclone: Path, tmp_path: Path) -> RcloneService:
    return RcloneService(fake_rclone, config_path=tmp_path / "rclone.conf")


def test_command_runs_as_user() -> None:
    svc = RcloneService("/usr/bin/rclone", user="seed")
    assert svc.command("listremotes") == [
        "sudo",
        "-u",
        "seed",
        "-H",
        "/usr/bin/rclone",
        "--config",
        "/home/seed/.config/rclone/rclone.conf",
        "listremotes",
    ]
    assert RcloneService("/usr/bin/rclone").command("version") == ["/usr/bin/rclone", "version"]


def test_parse_question_and_authorize_command() -> None:
    data = {
        "State": "s1",
        "Option": {
            "Name": "config_token",
            "Help": 'Run:\n\nrclone authorize "drive" "eyJ"\n\nThen paste',
            "Default": None,
            "Required": True,
            "IsPassword": False,
            "Examples": [{"Value": True, "Help": "yes"}],
        },
        "Error": "",
    }
    question = parse_question(data)
    assert isinstance(question, Question)
    assert question.is_token
    assert question.authorize_command == 'rclone authorize "drive" "eyJ"'
    assert question.examples == [{"value": "true", "help": "yes"}]
    assert question.as_dict()["authorize_command"] == question.authorize_command
    assert parse_question({"State": "", "Option": None, "Error": ""}) is None
    with pytest.raises(RcloneError, match="boom"):
        parse_question({"State": "", "Option": None, "Error": "boom"})


def test_available_and_empty_remotes(service: RcloneService) -> None:
    assert service.available()
    assert service.remotes() == []
    assert service.remote_types() == {}
    assert [p.name for p in service.providers()] == ["drive", "sftp"]


def test_unavailable_binary(tmp_path: Path) -> None:
    svc = RcloneService(tmp_path / "missing")
    assert not svc.available()
    with pytest.raises(RcloneError):
        svc.remotes()


def test_create_step_walks_the_state_machine(service: RcloneService) -> None:
    first = service.create_step("google", "drive")
    assert first is not None
    assert first.name == "client_id"
    second = service.create_step("google", "drive", state=first.state, result="")
    assert second is not None
    assert second.name == "config_is_local"
    assert second.exclusive
    third = service.create_step("google", "drive", state=second.state, result="false")
    assert third is not None
    assert third.is_token
    assert third.authorize_command == 'rclone authorize "drive" "eyJzY29wZSI6ImRyaXZlIn0"'
    retry = service.create_step("google", "drive", state=third.state, result="")
    assert retry is not None
    assert retry.error == "token is required"
    done = service.create_step("google", "drive", state=third.state, result="{token}")
    assert done is None
    assert service.remotes() == ["google"]
    assert service.remote_types() == {"google": "drive"}


def test_answer_loop_auto_answers_local_browser(service: RcloneService) -> None:
    asked: list[str] = []

    def ask(question: Question) -> str | None:
        asked.append(question.name)
        return "{token}" if question.is_token else None

    service.answer_loop("gd", "drive", ask)
    assert asked == ["client_id", "config_token"]  # config_is_local answered for the user
    log = [
        json.loads(line)
        for line in Path(service.binary)
        .parent.parent.joinpath("rclone.log")
        .read_text()
        .splitlines()
    ]
    answers = [args[args.index("--result") + 1] for args in log if "--result" in args]
    assert answers == ["", "false", "{token}"]


def test_answer_loop_raises_on_error(service: RcloneService) -> None:
    def ask(question: Question) -> str | None:
        return "bad" if question.name == "client_id" else None

    with pytest.raises(RcloneError, match="invalid value"):
        service.answer_loop("gd", "drive", ask)


def test_media_layout_and_delete(service: RcloneService) -> None:
    service.answer_loop("gd", "drive", lambda q: "{token}" if q.is_token else None)
    assert service.list_dirs("gd") == []
    assert service.ensure_media_layout("gd") == ["Media/Movies", "Media/TV", "Media/Music"]
    assert service.list_dirs("gd") == ["Media"]
    service.delete_remote("gd")
    assert service.remotes() == []
