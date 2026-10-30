"""Built-in and custom value validators.

Each validator takes the value and its parent mapping and returns ``None`` on
success, raises ``ValueError`` on failure, or raises ``ValidationWarning`` for
a non-fatal finding. The rules follow sb-go's ``custom_validators.go`` so the
engine rejects exactly what ``sb validate-config`` rejects.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
import zoneinfo
from collections.abc import Callable
from typing import Any

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
HOSTNAME_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?"
    r"(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$"
)
URL_RE = re.compile(r"^https?://[^\s]+$")
URL_CHARS_RE = re.compile(r"^[A-Za-z0-9\-._~!*'();:@&=+$,/?#\[\]%]+$")
SSH_KEY_TYPES = (
    "ssh-rsa",
    "ssh-dss",
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "sk-ssh-ed25519@openssh.com",
    "sk-ecdsa-sha2-nistp256@openssh.com",
)
ANSIBLE_TRUE = {"yes", "true", "on", "1"}
ANSIBLE_FALSE = {"no", "false", "off", "0"}
CRON_TIMES = {"annually", "daily", "hourly", "monthly", "reboot", "weekly", "yearly"}
RCLONE_TEMPLATES = {"dropbox", "google", "sftp", "nfs"}
PASSWORD_MIN_RECOMMENDED = 12


class ValidationWarning(Exception):
    """A finding that does not fail validation."""


Validator = Callable[[Any, dict[str, Any]], None]


def parse_ansible_bool(value: Any) -> bool | None:
    """Return the boolean an Ansible-style value represents, or ``None``."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ANSIBLE_TRUE:
            return True
        if lowered in ANSIBLE_FALSE:
            return False
    return None


def is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value == "")


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_RE.match(value))


def is_valid_hostname(value: str) -> bool:
    return 0 < len(value) <= 253 and bool(HOSTNAME_RE.match(value))


def is_valid_url(value: str) -> bool:
    return bool(URL_RE.match(value))


def is_authorized_key_line(line: str) -> bool:
    """Accept one ``authorized_keys`` line with a base64 key blob."""
    parts = line.strip().split()
    if len(parts) < 2:
        return False
    # An options prefix (e.g. ``no-pty``) may precede the key type.
    start = 0
    if parts[0] not in SSH_KEY_TYPES:
        start = 1
        if len(parts) < 3 or parts[1] not in SSH_KEY_TYPES:
            return False
    key_type, blob = parts[start], parts[start + 1]
    try:
        decoded = base64.b64decode(blob, validate=True)
    except (binascii.Error, ValueError):
        return False
    if len(decoded) < 4:
        return False
    length = int.from_bytes(decoded[:4], "big")
    return decoded[4 : 4 + length] == key_type.encode()


def is_ssh_key_or_url(value: str) -> bool:
    return is_valid_url(value) or is_authorized_key_line(value)


def validate_ssh_key_or_url(value: Any, _config: dict[str, Any]) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError("must be a string")
    if value == "":
        return
    if not is_ssh_key_or_url(value):
        raise ValueError("must be a valid SSH public key or URL")


def validate_password_strength(value: Any, _config: dict[str, Any]) -> None:
    if not isinstance(value, str):
        raise ValueError("password must be a string")
    if len(value) == 0:
        raise ValueError("password cannot be empty")


def password_strength_warning(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) == 0 or len(value) >= PASSWORD_MIN_RECOMMENDED:
        return None
    return (
        f"Password is shorter than {PASSWORD_MIN_RECOMMENDED} characters ({len(value)}). "
        "It's recommended to use a stronger password as some automated application setup "
        "flows may require it (Portainer skips user setup as an example)."
    )


def _non_empty_string(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    if isinstance(value, str) and value != "":
        return value
    return None


def parse_cloudflare_credentials(value: Any) -> dict[str, str] | None:
    """Return the configured credential set, ``None`` when unconfigured.

    Raises ``ValueError`` for mixed or incomplete credentials.
    """
    if not isinstance(value, dict):
        raise ValueError("cloudflare config must be an object")
    api_key = _non_empty_string(value, "api")
    email = _non_empty_string(value, "email")
    token = _non_empty_string(value, "scoped_token")
    if token and (api_key or email):
        raise ValueError("'scoped_token' cannot be combined with 'api' or 'email'")
    if token:
        return {"scoped_token": token}
    if not api_key and not email:
        return None
    if not api_key or not email:
        raise ValueError("both 'api' and 'email' must be provided together")
    return {"api": api_key, "email": email}


def validate_cloudflare_config(value: Any, config: dict[str, Any]) -> None:
    credentials = parse_cloudflare_credentials(value)
    if credentials is None:
        return
    user = config.get("user")
    if not isinstance(user, dict):
        raise ValueError("user config is required for Cloudflare validation")
    if not isinstance(user.get("domain"), str):
        raise ValueError("user domain is required for Cloudflare validation")


def parse_dockerhub_credentials(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, dict):
        raise ValueError("dockerhub config must be an object")
    user = _non_empty_string(value, "user")
    token = _non_empty_string(value, "token")
    if not user and not token:
        return None
    if not user or not token:
        raise ValueError("both 'user' and 'token' must be provided together")
    return user, token


def validate_dockerhub_config(value: Any, _config: dict[str, Any]) -> None:
    parse_dockerhub_credentials(value)


def validate_ansible_bool(value: Any, _config: dict[str, Any]) -> None:
    if isinstance(value, bool):
        return
    if not isinstance(value, str):
        raise ValueError(
            f"ansible boolean must be a string or boolean, got: {type(value).__name__}"
        )
    if value.lower() not in ANSIBLE_TRUE | ANSIBLE_FALSE:
        raise ValueError(
            f"must be a valid Ansible boolean (yes/no, true/false, on/off, 1/0), got: {value}"
        )


def validate_timezone(value: Any, _config: dict[str, Any]) -> None:
    if not isinstance(value, str):
        raise ValueError("timezone must be a string")
    if value.lower() == "auto":
        return
    try:
        zoneinfo.ZoneInfo(value)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(f"invalid timezone: {value}") from error


def validate_cron_time(value: Any, _config: dict[str, Any]) -> None:
    if not isinstance(value, str):
        raise ValueError("cron time must be a string")
    if value.lower() not in CRON_TIMES:
        raise ValueError(
            "must be a valid Ansible cron special time "
            f"(annually, daily, hourly, monthly, reboot, weekly, yearly), got: {value}"
        )


def validate_directory_path(value: Any, _config: dict[str, Any]) -> None:
    if not isinstance(value, str):
        raise ValueError("directory path must be a string")
    if value == "":
        raise ValueError("directory path cannot be empty")


def validate_rclone_template(value: Any, _config: dict[str, Any]) -> None:
    if not isinstance(value, str):
        raise ValueError("rclone template must be a string")
    if value.lower() in RCLONE_TEMPLATES:
        return
    if value.startswith("/"):
        if not os.path.exists(value):
            raise ValueError(f"rclone template file not found: {value}")
        return
    raise ValueError(
        f"must be one of 'dropbox', 'google', 'sftp', 'nfs', or a valid absolute file path, "
        f"got: {value}"
    )


def validate_whole_number(value: Any, _config: dict[str, Any]) -> None:
    if isinstance(value, bool):
        raise ValueError(f"must be a whole number (integer), got: {value}")
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if value != int(value):
            raise ValueError(f"must be a whole number (integer), got: {value} (has decimal part)")
        return
    if isinstance(value, str):
        try:
            int(value)
        except ValueError as error:
            raise ValueError(f"must be a whole number (integer), got: {value}") from error
        return
    raise ValueError(f"must be a whole number (integer), got: {type(value).__name__}")


def validate_number_type(value: Any) -> None:
    """``type: number``, which is stricter than ``validate_whole_number`` for floats."""
    if isinstance(value, bool):
        raise ValueError(f"must be a whole number (integer), got: {type(value).__name__}")
    if isinstance(value, int):
        return
    if isinstance(value, float):
        raise ValueError(f"must be a whole number (integer), got: {value}")
    if isinstance(value, str):
        try:
            int(value)
        except ValueError as error:
            raise ValueError(f"must be a whole number (integer), got: {value}") from error
        return
    raise ValueError(f"must be a whole number (integer), got: {type(value).__name__}")


def validate_float_type(value: Any) -> None:
    if isinstance(value, bool | int):
        raise ValueError(f"must be a float, got: {value}")
    if isinstance(value, float):
        return
    if isinstance(value, str):
        try:
            float(value)
        except ValueError as error:
            raise ValueError(f"must be a float, got: {value}") from error
        return
    raise ValueError(f"must be a float, got: {type(value).__name__}")


def validate_url(value: Any, _config: dict[str, Any]) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError("must be a string")
    if value == "":
        return
    if not is_valid_url(value):
        raise ValueError("must be a valid URL format (e.g., https://example.com)")
    if not URL_CHARS_RE.match(value):
        for index, char in enumerate(value):
            if not URL_CHARS_RE.match(char):
                raise ValueError(
                    f"contains invalid character '{char}' at position {index + 1}. URLs can "
                    "only contain letters, numbers, and these special characters: "
                    "-._~!*'();:@&=+$,/?#[]%"
                )


def validate_positive_number(value: Any, _config: dict[str, Any]) -> None:
    if isinstance(value, bool):
        raise ValueError(f"must be a number, got: {type(value).__name__}")
    if isinstance(value, int | float):
        if value <= 0:
            raise ValueError(f"must be greater than 0, got: {value}")
        return
    if isinstance(value, str):
        try:
            number = int(value)
        except ValueError as error:
            raise ValueError(f"must be a valid number, got: {value}") from error
        if number <= 0:
            raise ValueError(f"must be greater than 0, got: {number}")
        return
    raise ValueError(f"must be a number, got: {type(value).__name__}")


def _is_alnum(char: str) -> bool:
    return char.isascii() and char.isalnum()


def validate_subdomain_characters(subdomain: str) -> None:
    if len(subdomain) == 0:
        raise ValueError("subdomain cannot be empty")
    if len(subdomain) > 63:
        raise ValueError(f"subdomain cannot be longer than 63 characters, got {len(subdomain)}")
    previous_hyphen = False
    for index, char in enumerate(subdomain):
        if not (_is_alnum(char) or char == "-"):
            raise ValueError(
                f"subdomain contains invalid character '{char}' at position {index + 1}. "
                "Only letters, numbers, and hyphens are allowed"
            )
        if char == "-":
            if previous_hyphen:
                raise ValueError(
                    f"subdomain cannot contain consecutive hyphens at position {index + 1}"
                )
            previous_hyphen = True
        else:
            previous_hyphen = False
    if not _is_alnum(subdomain[0]):
        raise ValueError(f"subdomain must start with a letter or number, not '{subdomain[0]}'")
    if not _is_alnum(subdomain[-1]):
        raise ValueError(f"subdomain must end with a letter or number, not '{subdomain[-1]}'")


def validate_subdomain(value: Any, _config: dict[str, Any]) -> None:
    if not isinstance(value, str):
        raise ValueError("subdomain must be a string")
    validate_subdomain_characters(value)


def validate_hostname_strict(value: Any, _config: dict[str, Any]) -> None:
    if not isinstance(value, str):
        raise ValueError("hostname must be a string")
    if not is_valid_hostname(value):
        raise ValueError("invalid hostname format")
    for index, label in enumerate(value.split(".")):
        try:
            validate_subdomain_characters(label)
        except ValueError as error:
            raise ValueError(
                f"invalid characters in hostname label {index + 1} ('{label}'): {error}"
            ) from error


def make_rclone_remote_validator(
    list_remotes: Callable[[], list[str] | None],
) -> Validator:
    """Build ``validate_rclone_remote`` around a remote lister.

    ``list_remotes`` returns the configured remote names, or ``None`` when
    rclone or its config is unavailable, which downgrades to a warning like sb.
    """

    def validate_rclone_remote(value: Any, _config: dict[str, Any]) -> None:
        if not isinstance(value, str):
            raise ValueError("rclone remote must be a string")
        remote_name = value.split(":", 1)[0]
        try:
            remotes = list_remotes()
        except OSError as error:
            raise ValidationWarning(f"rclone remote validation skipped: {error}") from error
        if remotes is None:
            raise ValidationWarning("rclone remote validation skipped: rclone is not available")
        if remote_name not in remotes:
            raise ValueError(f"rclone remote '{remote_name}' not found in configuration")

    return validate_rclone_remote


def no_rclone_remotes() -> list[str] | None:
    return None


BUILTIN_TYPE_VALIDATORS: dict[str, str] = {
    "ansible_bool": "validate_ansible_bool",
    "subdomain": "validate_subdomain",
    "hostname": "validate_hostname",
    "directory_path": "validate_directory_path",
    "url": "validate_url",
    "timezone": "validate_timezone",
    "cron_time": "validate_cron_time",
    "rclone_template": "validate_rclone_template",
    "ssh_key_or_url": "validate_ssh_key_or_url",
    "password": "validate_password_strength",
}


def default_validators(
    list_remotes: Callable[[], list[str] | None] = no_rclone_remotes,
) -> dict[str, Validator]:
    return {
        "validate_ssh_key_or_url": validate_ssh_key_or_url,
        "validate_password_strength": validate_password_strength,
        "validate_cloudflare_config": validate_cloudflare_config,
        "validate_dockerhub_config": validate_dockerhub_config,
        "validate_rclone_remote": make_rclone_remote_validator(list_remotes),
        "validate_ansible_bool": validate_ansible_bool,
        "validate_timezone": validate_timezone,
        "validate_cron_time": validate_cron_time,
        "validate_directory_path": validate_directory_path,
        "validate_rclone_template": validate_rclone_template,
        "validate_whole_number": validate_whole_number,
        "validate_url": validate_url,
        "validate_positive_number": validate_positive_number,
        "validate_subdomain": validate_subdomain,
        "validate_hostname": validate_hostname_strict,
    }


API_VALIDATORS = {"validate_cloudflare_config", "validate_dockerhub_config"}
