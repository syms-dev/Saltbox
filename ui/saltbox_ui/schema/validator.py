"""Schema loader and validator.

Reads the ``schema/*.schema.yml`` files shipped with Saltbox and checks a
configuration mapping against them with the same semantics as sb-go's
``yaml_schema.go``: required and conditional fields, unknown keys, formats,
lengths, forbidden defaults, built-in type validators and custom validators.

Unlike sb, which stops at the first error, this collects every error so a UI
can show them all at once. Live API checks (Cloudflare, Docker Hub) are
pluggable through ``ValidationContext.api_checks``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..yamlio import load_plain
from . import validators as v

_UNSET = object()


@dataclass
class Rule:
    type: str = ""
    required: bool = False
    format: str = ""
    min_length: int = 0
    max_length: int = 0
    not_equals: Any = _UNSET
    required_with: list[str] = field(default_factory=list)
    required_when_true: list[str] = field(default_factory=list)
    validate_when_true: list[str] = field(default_factory=list)
    custom_validator: str = ""
    properties: dict[str, Rule] | None = None
    items: Rule | None = None
    description: str = ""
    example: Any = None

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> Rule:
        properties = raw.get("properties")
        items = raw.get("items")
        return cls(
            type=str(raw.get("type", "")),
            required=bool(raw.get("required", False)),
            format=str(raw.get("format", "")),
            min_length=int(raw.get("min_length", 0) or 0),
            max_length=int(raw.get("max_length", 0) or 0),
            not_equals=raw.get("not_equals", _UNSET),
            required_with=list(raw.get("required_with", []) or []),
            required_when_true=list(raw.get("required_when_true", []) or []),
            validate_when_true=list(raw.get("validate_when_true", []) or []),
            custom_validator=str(raw.get("custom_validator", "") or ""),
            properties=(
                {str(k): Rule.from_mapping(val) for k, val in properties.items()}
                if isinstance(properties, dict)
                else None
            ),
            items=Rule.from_mapping(items) if isinstance(items, dict) else None,
            description=str(raw.get("description", "") or ""),
            example=raw.get("example"),
        )


@dataclass(frozen=True)
class Issue:
    path: str
    message: str
    level: str = "error"  # "error" or "warning"

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "message": self.message, "level": self.level}


ApiCheck = Callable[[Any, dict[str, Any]], None]


@dataclass
class ValidationContext:
    """Dependencies the validator needs from the outside world."""

    validators: dict[str, v.Validator] = field(default_factory=v.default_validators)
    api_checks: dict[str, ApiCheck] = field(default_factory=dict)
    run_api_checks: bool = False


class Schema:
    def __init__(self, rules: dict[str, Rule]):
        self.rules = rules

    def validate(self, config: Any, context: ValidationContext | None = None) -> list[Issue]:
        ctx = context or ValidationContext()
        issues: list[Issue] = []
        if not isinstance(config, dict):
            return [Issue("", "configuration must be a mapping")]
        self._validate_object(config, self.rules, "", ctx, issues)
        return issues

    # -- object and field walkers ----------------------------------------
    def _validate_object(
        self,
        obj: dict[str, Any],
        rules: dict[str, Rule],
        path: str,
        ctx: ValidationContext,
        issues: list[Issue],
    ) -> None:
        for name, rule in rules.items():
            field_path = _join(path, name)
            exists = name in obj
            if _is_required(rule, obj) and not exists:
                issues.append(Issue(field_path, f"field '{field_path}' is required"))
                continue
            if not exists or not _should_validate(rule, obj):
                continue
            self._validate_field(obj[name], rule, field_path, obj, ctx, issues)
        for name in obj:
            if name not in rules:
                issues.append(Issue(_join(path, name), f"unknown field '{_join(path, name)}'"))

    def _validate_field(
        self,
        value: Any,
        rule: Rule,
        path: str,
        parent: dict[str, Any],
        ctx: ValidationContext,
        issues: list[Issue],
    ) -> None:
        before = len(issues)
        if (
            rule.not_equals is not _UNSET
            and type(value) is type(rule.not_equals)
            and value == rule.not_equals
        ):
            issues.append(
                Issue(path, f"field '{path}' must not equal its configured default value")
            )
        if rule.required_with:
            present = any(
                not v.is_empty(parent.get(name)) for name in rule.required_with if name in parent
            )
            if present and v.is_empty(value):
                issues.append(
                    Issue(
                        path,
                        f"field '{path}' is required when any of {rule.required_with} are present",
                    )
                )
        if len(issues) > before:
            return
        if not rule.required and v.is_empty(value):
            return

        if rule.format:
            error = _check_format(value, rule.format, path)
            if error:
                issues.append(Issue(path, error))
                return
        if rule.min_length or rule.max_length:
            error = _check_length(value, rule, path)
            if error:
                issues.append(Issue(path, error))
                return

        try:
            if rule.type == "number":
                v.validate_number_type(value)
            elif rule.type == "float":
                v.validate_float_type(value)
        except ValueError as error:
            issues.append(Issue(path, f"field '{path}': {error}"))
            return

        builtin = v.BUILTIN_TYPE_VALIDATORS.get(rule.type)
        if builtin:
            if not self._run_validator(builtin, value, parent, path, ctx, issues):
                return
            if builtin == "validate_password_strength":
                warning = v.password_strength_warning(value)
                if warning:
                    issues.append(Issue(path, warning, "warning"))

        if rule.custom_validator:
            name = rule.custom_validator
            if name in ctx.validators:
                if not self._run_validator(name, value, parent, path, ctx, issues):
                    return
            else:
                issues.append(Issue(path, f"unknown custom validator '{name}' for field '{path}'"))
                return
            if ctx.run_api_checks and name in ctx.api_checks:
                try:
                    ctx.api_checks[name](value, parent)
                except v.ValidationWarning as warning:
                    issues.append(Issue(path, str(warning), "warning"))
                except Exception as error:
                    issues.append(Issue(path, f"{path}: {error}"))
                    return

        if rule.type == "object" and rule.properties is not None and isinstance(value, dict):
            self._validate_object(value, rule.properties, path, ctx, issues)
        if rule.type == "array" and rule.items is not None and isinstance(value, list):
            for index, item in enumerate(value):
                self._validate_field(item, rule.items, f"{path}[{index}]", parent, ctx, issues)

    @staticmethod
    def _run_validator(
        name: str,
        value: Any,
        parent: dict[str, Any],
        path: str,
        ctx: ValidationContext,
        issues: list[Issue],
    ) -> bool:
        validator = ctx.validators.get(name)
        if validator is None:
            issues.append(Issue(path, f"unknown validator '{name}' for field '{path}'"))
            return False
        try:
            validator(value, parent)
        except v.ValidationWarning as warning:
            issues.append(Issue(path, str(warning), "warning"))
        except ValueError as error:
            issues.append(Issue(path, f"field '{path}': {error}"))
            return False
        return True

    # -- example generation ----------------------------------------------
    def field_rules(self) -> dict[str, Rule]:
        return self.rules


def _join(base: str, name: str) -> str:
    return f"{base}.{name}" if base else name


def _is_required(rule: Rule, parent: dict[str, Any]) -> bool:
    if rule.required:
        return True
    for name in rule.required_when_true:
        if name in parent and v.parse_ansible_bool(parent[name]) is True:
            return True
    return False


def _should_validate(rule: Rule, parent: dict[str, Any]) -> bool:
    if not rule.validate_when_true:
        return True
    return any(
        name in parent and v.parse_ansible_bool(parent[name]) is True
        for name in rule.validate_when_true
    )


def _check_format(value: Any, fmt: str, path: str) -> str | None:
    if not isinstance(value, str):
        return f"field '{path}' must be a string"
    if fmt == "email":
        return None if v.is_valid_email(value) else f"field '{path}' must be a valid email address"
    if fmt == "hostname":
        return None if v.is_valid_hostname(value) else f"field '{path}' must be a valid hostname"
    if fmt == "url":
        return None if v.is_valid_url(value) else f"field '{path}' must be a valid URL"
    return f"unknown format '{fmt}' for field '{path}'"


def _check_length(value: Any, rule: Rule, path: str) -> str | None:
    if not isinstance(value, str):
        return f"field '{path}' must be a string"
    length = len(value)
    if rule.min_length and length < rule.min_length:
        return f"field '{path}' must be at least {rule.min_length} characters long, got {length}"
    if rule.max_length and length > rule.max_length:
        return f"field '{path}' must be at most {rule.max_length} characters long, got {length}"
    return None


def load_schema(path: Path) -> Schema:
    raw = load_plain(Path(path))
    if not isinstance(raw, dict):
        raise ValueError(f"schema {path} must be a mapping")
    return Schema({str(k): Rule.from_mapping(val) for k, val in raw.items()})
