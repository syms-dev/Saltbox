import pytest

from saltbox_ui.schema import validators as v

ED25519 = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGb0oZ4m4V5d9Zq8l7d7Qf2l7Zg0jWc0v3o9bVt9yY0o user@host"
)


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("https://github.com/charlie.keys", True),
        (ED25519, True),
        ("no-pty " + ED25519, True),
        ("ssh-rsa notbase64!! x", False),
        ("ssh-ed25519 QUJD x", False),
        ("just text", False),
    ],
)
def test_ssh_key_or_url(value, ok):
    assert v.is_ssh_key_or_url(value) is ok


def test_ansible_bool():
    for value in ("yes", "No", "on", "0", True, False):
        v.validate_ansible_bool(value, {})
    with pytest.raises(ValueError):
        v.validate_ansible_bool("maybe", {})
    with pytest.raises(ValueError):
        v.validate_ansible_bool(1, {})
    assert v.parse_ansible_bool("off") is False
    assert v.parse_ansible_bool("x") is None


def test_subdomain_rules():
    v.validate_subdomain("login", {})
    v.validate_subdomain("tv-4k", {})
    for bad in ("", "-a", "a-", "a--b", "a_b", "x" * 64):
        with pytest.raises(ValueError):
            v.validate_subdomain(bad, {})


def test_hostname_rules():
    v.validate_hostname_strict("example.com", {})
    v.validate_hostname_strict("home.example.co.uk", {})
    with pytest.raises(ValueError):
        v.validate_hostname_strict("bad_host.com", {})
    with pytest.raises(ValueError):
        v.validate_hostname_strict("-x.com", {})


def test_timezone_and_cron():
    v.validate_timezone("auto", {})
    v.validate_timezone("Europe/Copenhagen", {})
    with pytest.raises(ValueError):
        v.validate_timezone("Mars/Olympus", {})
    v.validate_cron_time("Weekly", {})
    with pytest.raises(ValueError):
        v.validate_cron_time("fortnightly", {})


def test_cloudflare_credential_modes():
    assert v.parse_cloudflare_credentials({"api": "", "email": "", "scoped_token": ""}) is None
    assert v.parse_cloudflare_credentials({"scoped_token": "t"}) == {"scoped_token": "t"}
    assert v.parse_cloudflare_credentials({"api": "k", "email": "e@x.io"}) == {
        "api": "k",
        "email": "e@x.io",
    }
    with pytest.raises(ValueError):
        v.parse_cloudflare_credentials({"api": "k", "scoped_token": "t"})
    with pytest.raises(ValueError):
        v.parse_cloudflare_credentials({"api": "k"})
    with pytest.raises(ValueError):
        v.validate_cloudflare_config({"scoped_token": "t"}, {})


def test_dockerhub_pairs():
    assert v.parse_dockerhub_credentials({"user": "", "token": ""}) is None
    assert v.parse_dockerhub_credentials({"user": "u", "token": "t"}) == ("u", "t")
    with pytest.raises(ValueError):
        v.parse_dockerhub_credentials({"user": "u"})


def test_rclone_template_and_remote(tmp_path):
    v.validate_rclone_template("google", {})
    custom = tmp_path / "custom.j2"
    custom.write_text("x")
    v.validate_rclone_template(str(custom), {})
    with pytest.raises(ValueError):
        v.validate_rclone_template("/nope/missing.j2", {})
    with pytest.raises(ValueError):
        v.validate_rclone_template("box", {})

    remote = v.make_rclone_remote_validator(lambda: ["google", "dropbox"])
    remote("google:Media", {})
    with pytest.raises(ValueError):
        remote("nas:/x", {})
    missing = v.make_rclone_remote_validator(v.no_rclone_remotes)
    with pytest.raises(v.ValidationWarning):
        missing("google", {})


def test_numbers_and_urls():
    v.validate_number_type(22)
    v.validate_number_type("22")
    with pytest.raises(ValueError):
        v.validate_number_type(2.5)
    v.validate_whole_number(2.0, {})
    with pytest.raises(ValueError):
        v.validate_whole_number(True, {})
    v.validate_url("https://example.com/path?x=1", {})
    with pytest.raises(ValueError):
        v.validate_url("ftp://example.com", {})
    with pytest.raises(ValueError):
        v.validate_url("https://exa mple.com", {})
    v.validate_positive_number("3", {})
    with pytest.raises(ValueError):
        v.validate_positive_number(0, {})


def test_password_warning():
    assert v.password_strength_warning("short") is not None
    assert v.password_strength_warning("longenoughpassword") is None
    with pytest.raises(ValueError):
        v.validate_password_strength("", {})
