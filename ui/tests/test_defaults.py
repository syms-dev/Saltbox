from pathlib import Path

from saltbox_ui.catalog import parse_role_defaults
from saltbox_ui.catalog.defaults import infer_type


def _defaults(repo_root: Path, role: str):
    return parse_role_defaults(role, repo_root / "roles" / role / "defaults" / "main.yml")


def test_sonarr_sections_scopes_and_help(repo_root: Path):
    role = _defaults(repo_root, "sonarr")
    assert role.supports_instances
    assert role.instances_var == "sonarr_instances"
    assert role.default_instances == ["sonarr"]
    assert role.sections[:3] == ["Basics", "Settings", "Paths"]
    fields = role.by_name()
    external = fields["sonarr_role_allow_external_auth_without_sso"]
    assert external.type == "bool"
    assert external.section == "Settings"
    assert external.scope == "role"
    assert external.suffix == "_allow_external_auth_without_sso"
    assert external.help[0].startswith("Allow External authentication without Traefik SSO")
    assert role.instance_key(external, "sonarr4k") == "sonarr4k_allow_external_auth_without_sso"
    assert fields["sonarr_instances"].scope == "instances"
    assert fields["sonarr_role_docker_image_tag"].type == "string"
    assert fields["sonarr_role_docker_image_tag"].value == "release"
    assert fields["sonarr_role_web_port"].type == "string"


def test_hidden_fields(repo_root: Path):
    fields = _defaults(repo_root, "sonarr").by_name()
    assert fields["sonarr_role_allowed_hosts_public_fqdn_default"].hidden_reason == "do-not-edit"
    assert fields["sonarr_role_allowed_hosts_public"].hidden_reason == "skip-docs"
    assert fields["sonarr_role_docker_envs"].hidden_reason == "aggregate"
    assert fields["sonarr_role_docker_envs_custom"].hidden is False
    assert fields["sonarr_role_docker_image"].hidden is False
    visible = {f.name for f in _defaults(repo_root, "sonarr").visible()}
    assert "sonarr_role_docker_envs" not in visible
    assert "sonarr_role_docker_envs_custom" in visible


def test_jinja_type_inference(repo_root: Path):
    fields = _defaults(repo_root, "sonarr").by_name()
    assert fields["sonarr_role_docker_volumes"].jinja
    assert fields["sonarr_role_docker_volumes"].type == "list"
    assert fields["sonarr_role_docker_envs"].type == "dict"
    assert fields["sonarr_role_dns_proxy"].type == "bool"
    assert fields["sonarr_role_web_url"].type == "string"
    assert fields["sonarr_role_traefik_enabled"].type == "bool"
    assert infer_type("x_role_web_port", "{{ y }}", "{{ y }}") == "string (number)"
    assert infer_type("x_role_args", "{{ y | saltbox_argv }}", "") == "list"
    assert infer_type("plain", 3, "3") == "int"


def test_subsections_and_global_help(repo_root: Path):
    fields = _defaults(repo_root, "authelia").by_name()
    level = fields["authelia_role_log_level"]
    assert level.subsection == "Logs"
    assert any("authelia.com/configuration/miscellaneous/logging" in line for line in level.help)
    local = fields["authelia_role_log_max_backups"]
    assert local.help == ["Logrotate configuration variable"]
    lookup = fields["authelia_role_access_control_whitelist_rules_lookup"]
    assert lookup.hidden


def test_role_without_instances(repo_root: Path):
    role = _defaults(repo_root, "traefik")
    assert not role.supports_instances
    assert "Config" in role.sections


def test_every_role_parses(repo_root: Path):
    roles_dir = repo_root / "roles"
    parsed = 0
    for path in sorted(roles_dir.glob("*/defaults/main.yml")):
        role = parse_role_defaults(path.parent.parent.name, path)
        assert role.fields or role.sections == []
        parsed += 1
    assert parsed > 80
