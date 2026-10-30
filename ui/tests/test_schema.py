from pathlib import Path

from saltbox_ui.schema import Schema, ValidationContext, load_schema
from saltbox_ui.schema.validator import Rule
from saltbox_ui.schema.validators import ValidationWarning, default_validators
from saltbox_ui.yamlio import load_plain


def _ctx(remotes=None) -> ValidationContext:
    return ValidationContext(validators=default_validators(lambda: remotes))


def _errors(issues):
    return [i.message for i in issues if i.level == "error"]


def test_accounts_default_fails_on_placeholders(repo_root: Path):
    schema = load_schema(repo_root / "schema" / "accounts.schema.yml")
    config = load_plain(repo_root / "defaults" / "accounts.yml.default")
    messages = _errors(schema.validate(config, _ctx()))
    assert any("user.domain" in m and "default value" in m for m in messages)
    assert any("user.email" in m and "default value" in m for m in messages)
    assert not any("user.pass" in m for m in messages), messages
    assert not any("cloudflare" in m for m in messages)


def test_accounts_valid_and_warnings(repo_root: Path):
    schema = load_schema(repo_root / "schema" / "accounts.schema.yml")
    config = {
        "user": {
            "name": "seed",
            "pass": "short",
            "domain": "example.com",
            "email": "me@example.com",
            "ssh_key": "https://github.com/me.keys",
        },
        "cloudflare": {"api": "", "email": "", "scoped_token": "tok"},
        "dockerhub": {"user": "", "token": ""},
        "apprise": None,
    }
    issues = schema.validate(config, _ctx())
    assert _errors(issues) == []
    assert [i.level for i in issues] == ["warning"]
    assert "shorter than 12" in issues[0].message


def test_accounts_unknown_field_and_required_with(repo_root: Path):
    schema = load_schema(repo_root / "schema" / "accounts.schema.yml")
    config = {
        "user": {"name": "seed", "pass": "password12345678", "domain": "x.io", "email": "a@b.co"},
        "cloudflare": {"api": "key", "email": "", "scoped_token": ""},
        "plex": {"user": "x"},
    }
    messages = _errors(schema.validate(config, _ctx()))
    assert any("unknown field 'plex'" in m for m in messages)
    assert any("both 'api' and 'email' must be provided together" in m for m in messages)


def test_required_with_on_plain_fields():
    schema = Schema(
        {
            "a": Rule(type="string", required_with=["b"]),
            "b": Rule(type="string", required_with=["a"]),
        }
    )
    assert schema.validate({"a": "x", "b": "y"}, _ctx()) == []
    assert schema.validate({"a": "", "b": ""}, _ctx()) == []
    messages = _errors(schema.validate({"a": "x", "b": ""}, _ctx()))
    assert messages == ["field 'b' is required when any of ['a'] are present"]


def test_settings_default_is_valid(repo_root: Path):
    # sb's settings schema does not check that remotes exist in rclone.conf;
    # the engine does that separately in the rclone service.
    schema = load_schema(repo_root / "schema" / "settings.schema.yml")
    config = load_plain(repo_root / "defaults" / "settings.yml.default")
    assert schema.validate(config, _ctx(None)) == []
    config["rclone"]["remotes"][0]["settings"]["template"] = "box"
    messages = _errors(schema.validate(config, _ctx(None)))
    assert any("remotes[0].settings.template" in m for m in messages)


def test_settings_remotes_skipped_when_rclone_disabled(repo_root: Path):
    schema = load_schema(repo_root / "schema" / "settings.schema.yml")
    config = load_plain(repo_root / "defaults" / "settings.yml.default")
    config["rclone"]["enabled"] = "no"
    del config["rclone"]["remotes"]
    assert schema.validate(config, _ctx(None)) == []
    config["rclone"]["enabled"] = "yes"
    messages = _errors(schema.validate(config, _ctx(None)))
    assert any("rclone.remotes" in m and "required" in m for m in messages)


def test_other_defaults_are_valid(repo_root: Path):
    for name in ("adv_settings", "backup_config", "hetzner_vlan"):
        schema = load_schema(repo_root / "schema" / f"{name}.schema.yml")
        config = load_plain(repo_root / "defaults" / f"{name}.yml.default")
        assert _errors(schema.validate(config, _ctx())) == [], name


def test_adv_settings_type_checks(repo_root: Path):
    schema = load_schema(repo_root / "schema" / "adv_settings.schema.yml")
    config = load_plain(repo_root / "defaults" / "adv_settings.yml.default")
    config["dns"]["ipv6"] = "sometimes"
    config["system"]["timezone"] = "Nowhere/Land"
    config["traefik"]["subdomains"]["dash"] = "bad_sub"
    config["traefik"]["cert"]["additional_domains"] = ["ok.example.com", "bad_host"]
    messages = _errors(schema.validate(config, _ctx()))
    assert any("dns.ipv6" in m for m in messages)
    assert any("system.timezone" in m for m in messages)
    assert any("traefik.subdomains.dash" in m for m in messages)
    assert any("additional_domains[1]" in m for m in messages)
    assert not any("additional_domains[0]" in m for m in messages)


def test_backup_number_field(repo_root: Path):
    schema = load_schema(repo_root / "schema" / "backup_config.schema.yml")
    config = load_plain(repo_root / "defaults" / "backup_config.yml.default")
    config["backup"]["rsync"]["port"] = "twenty-two"
    messages = _errors(schema.validate(config, _ctx()))
    assert any("backup.rsync.port" in m and "whole number" in m for m in messages)


def test_api_checks_run_only_when_enabled():
    schema = Schema(
        {
            "cloudflare": Rule(
                type="object",
                custom_validator="validate_cloudflare_config",
                properties={"scoped_token": Rule(type="string")},
            ),
            "user": Rule(type="object", properties={"domain": Rule(type="string")}),
        }
    )
    calls = []

    def fake_check(value, config):
        calls.append(value)
        raise ValidationWarning("would call the API")

    config = {"cloudflare": {"scoped_token": "t"}, "user": {"domain": "x.io"}}
    ctx = ValidationContext(api_checks={"validate_cloudflare_config": fake_check})
    assert schema.validate(config, ctx) == []
    ctx.run_api_checks = True
    issues = schema.validate(config, ctx)
    assert calls == [{"scoped_token": "t"}]
    assert issues[0].level == "warning"
