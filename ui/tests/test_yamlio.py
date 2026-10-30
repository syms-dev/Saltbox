from pathlib import Path

from saltbox_ui.yamlio import (
    coerce_scalar,
    dump_text,
    find_duplicate_keys,
    get_path,
    load_text,
    load_yaml,
    save_yaml,
    set_path,
    to_plain,
)

SAMPLE = """---
# Leading comment
user:
  name: seed  # inline
  pass: "quoted value"
rclone:
  enabled: yes
  remotes:
    - remote: google
"""


def test_round_trip_preserves_comments_and_quotes():
    data = load_text(SAMPLE)
    data["user"]["name"] = "chaz"
    out = dump_text(data)
    assert "# Leading comment" in out
    assert "# inline" in out
    assert 'pass: "quoted value"' in out
    assert "name: chaz" in out
    assert "enabled: yes" in out


def test_save_keeps_mode(tmp_path: Path):
    path = tmp_path / "accounts.yml"
    path.write_text(SAMPLE)
    path.chmod(0o600)
    data = load_yaml(path)
    set_path(data, "user.email", "a@b.co")
    save_yaml(path, data)
    assert path.stat().st_mode & 0o777 == 0o600
    assert get_path(load_yaml(path), "user.email") == "a@b.co"
    assert path.read_text().startswith("---")


def test_save_new_file_gets_header(tmp_path: Path):
    path = tmp_path / "localhost.yml"
    data = load_text("a: 1\n")
    save_yaml(path, data, header="---\n# hello\n")
    assert path.read_text() == "---\n# hello\na: 1\n"


def test_duplicate_keys_are_reported_with_paths():
    text = "user:\n  name: a\n  name: b\nplex: 1\nplex: 2\n"
    found = find_duplicate_keys(text)
    assert found == ["user.name (appears 2 times)", "plex (appears 2 times)"]
    assert find_duplicate_keys(SAMPLE) == []


def test_to_plain_and_coerce():
    data = load_text(SAMPLE)
    plain = to_plain(data)
    assert plain["rclone"]["remotes"] == [{"remote": "google"}]
    assert coerce_scalar("yes") == "yes"
    assert coerce_scalar("true") is True
    assert coerce_scalar("12") == 12
    assert coerce_scalar("hello") == "hello"
    assert coerce_scalar("[a, b]") == ["a", "b"]
    assert coerce_scalar("not: [valid") == "not: [valid"
