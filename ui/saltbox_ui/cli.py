"""``sbx``: the engine as a JSON command line.

Every command prints one JSON document so the output can be piped into
``jq`` or consumed by tests. Exit status is 0 on success, 1 on a handled
error, 2 on usage errors. Validation returns 3 when errors were found.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from . import __version__
from .catalog import Catalog
from .config import ConfigService, Inventory
from .config.service import CONFIG_FILES
from .layout import Layout
from .runner import JobRunning, SbRunner
from .state import (
    cached_tags,
    disk_usage,
    list_containers,
    list_fact_roles,
    mounts,
    read_motd_services,
    read_port_assignments,
    read_role_facts,
    reboot_required,
    systemd_units,
)
from .state.facts import read_all_facts


def emit(data: Any) -> None:
    json.dump(data, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sbx", description="Saltbox UI engine, JSON output")
    parser.add_argument("--version", action="version", version=f"sbx {__version__}")
    sub = parser.add_subparsers(dest="group", required=True)

    sub.add_parser("layout", help="show resolved paths")

    config = sub.add_parser("config", help="configuration files").add_subparsers(
        dest="action", required=True
    )
    p = config.add_parser("show", help="print a config file as JSON")
    p.add_argument("name", choices=sorted(CONFIG_FILES))
    p = config.add_parser("validate", help="validate config files")
    p.add_argument("name", nargs="?", choices=sorted(CONFIG_FILES))
    p.add_argument("--api", action="store_true", help="also run live credential checks")
    p = config.add_parser("get", help="read a dotted key")
    p.add_argument("name", choices=sorted(CONFIG_FILES))
    p.add_argument("key")
    p = config.add_parser("set", help="write a dotted key (YAML scalar)")
    p.add_argument("name", choices=sorted(CONFIG_FILES))
    p.add_argument("key")
    p.add_argument("value")
    p = config.add_parser("init", help="create a config file from its default if missing")
    p.add_argument("name", choices=sorted(CONFIG_FILES))

    inv = sub.add_parser("inventory", help="localhost.yml overrides").add_subparsers(
        dest="action", required=True
    )
    inv.add_parser("show")
    p = inv.add_parser("instances")
    p.add_argument("role")
    p = inv.add_parser("overrides")
    p.add_argument("role")
    p = inv.add_parser("set")
    p.add_argument("key")
    p.add_argument("value")
    p = inv.add_parser("unset")
    p.add_argument("key")

    cat = sub.add_parser("catalog", help="apps, roles, tags, fields").add_subparsers(
        dest="action", required=True
    )
    p = cat.add_parser("apps")
    p.add_argument("--all", action="store_true", help="include core and hidden roles")
    cat.add_parser("roles")
    cat.add_parser("profiles")
    cat.add_parser("categories")
    p = cat.add_parser("fields")
    p.add_argument("role")
    p.add_argument("--repo", default="saltbox", choices=["saltbox", "sandbox"])
    p.add_argument("--all", action="store_true", help="include hidden fields")

    state = sub.add_parser("state", help="runtime state").add_subparsers(
        dest="action", required=True
    )
    p = state.add_parser("facts")
    p.add_argument("role", nargs="?")
    p.add_argument("--secrets", action="store_true", help="do not redact secrets")
    state.add_parser("ports")
    state.add_parser("mounts")
    state.add_parser("disks")
    state.add_parser("units")
    state.add_parser("containers")
    state.add_parser("tags")
    p = state.add_parser("motd")
    p.add_argument("--secrets", action="store_true")
    state.add_parser("host")

    run = sub.add_parser("run", help="run sb").add_subparsers(dest="action", required=True)
    p = run.add_parser("install")
    p.add_argument("tags", help="comma separated")
    p.add_argument("--skip-tags", default="")
    p.add_argument("-e", "--extra-vars", action="append", default=[])
    p.add_argument("-v", "--verbose", action="count", default=0)
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="print the command only")
    p = run.add_parser("update")
    p.add_argument("--dry-run", action="store_true")
    run.add_parser("jobs")
    p = run.add_parser("log")
    p.add_argument("job_id")
    run.add_parser("status")

    inst = sub.add_parser("install", help="installer plan and preflight").add_subparsers(
        dest="action", required=True
    )
    inst.add_parser("preflight", help="run the preflight checks")
    inst.add_parser("plan", help="show the saved install plan (secrets redacted)")
    inst.add_parser("discard", help="delete the saved install plan")
    p = inst.add_parser("apply", help="write the saved plan into the config files")
    p.add_argument("--validate", action="store_true")
    inst.add_parser("tags", help="print the tags the plan would install")

    tui = sub.add_parser("tui", help="start the terminal UI")
    tui.add_argument("--installer", action="store_true", default=True)

    daemon = sub.add_parser("daemon", help="the web daemon: unit, route, status")
    daemon_sub = daemon.add_subparsers(dest="action", required=True)
    p = daemon_sub.add_parser("install", help="write the systemd unit and enable the daemon")
    p.add_argument("--web", help="directory with the built web app")
    p.add_argument("--no-start", action="store_true")
    p = daemon_sub.add_parser("enable", help="token, Traefik route, unit and start: the web face")
    p.add_argument("--subdomain", default="saltbox")
    p.add_argument("--web", help="directory with the built web app")
    p.add_argument("--no-start", action="store_true")
    p = daemon_sub.add_parser("route", help="write the Traefik route for saltbox.<domain>")
    p.add_argument("--subdomain", default="saltbox")
    p.add_argument("--traefik-dir", help="Traefik config directory (default: <appdata>/traefik)")
    daemon_sub.add_parser("unit", help="print the systemd unit")
    daemon_sub.add_parser("url", help="print the web URL")
    daemon_sub.add_parser("token", help="print the API token (root)")
    daemon_sub.add_parser("status", help="systemd status of the daemon")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    layout = Layout.from_env()
    try:
        return _dispatch(args, layout)
    except BrokenPipeError:  # piped into head and the like
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115 - keep the interpreter quiet at exit
        return 0
    except JobRunning as error:
        emit({"error": str(error)})
        return 1
    except (OSError, ValueError, KeyError) as error:
        emit({"error": str(error)})
        return 1


def _dispatch(args: argparse.Namespace, layout: Layout) -> int:
    if args.group == "daemon":
        return _daemon(args, layout)
    if args.group == "layout":
        emit(layout.as_dict())
        return 0

    if args.group == "config":
        service = ConfigService(layout)
        if args.action == "show":
            emit({"source": service.source(args.name), "data": service.load_plain(args.name)})
        elif args.action == "validate":
            names = [args.name] if args.name else None
            if names:
                results = {n: service.validate(n, api_checks=args.api) for n in names}
            else:
                results = service.validate_all(api_checks=args.api)
            payload = {n: [i.as_dict() for i in issues] for n, issues in results.items()}
            has_errors = any(i.level == "error" for issues in results.values() for i in issues)
            emit({"ok": not has_errors, "results": payload})
            return 3 if has_errors else 0
        elif args.action == "get":
            emit({"key": args.key, "value": service.get(args.name, args.key)})
        elif args.action == "set":
            service.set(args.name, args.key, args.value)
            emit({"key": args.key, "value": service.get(args.name, args.key)})
        elif args.action == "init":
            emit(
                {"created": service.ensure_exists(args.name), "path": str(service.path(args.name))}
            )
        return 0

    if args.group == "inventory":
        inventory = Inventory(layout.inventory)
        catalog = Catalog(layout)
        if args.action == "show":
            emit(inventory.as_dict())
        elif args.action == "instances":
            defaults = catalog.defaults(args.role)
            default = defaults.default_instances if defaults else [args.role]
            emit({"role": args.role, "instances": inventory.instances(args.role, default)})
        elif args.action == "overrides":
            defaults = catalog.defaults(args.role)
            default = defaults.default_instances if defaults else [args.role]
            instances = inventory.instances(args.role, default)
            emit(inventory.overrides_for(args.role, instances))
        elif args.action == "set":
            inventory.set(args.key, args.value)
            emit({"key": args.key, "value": inventory.get(args.key)})
        elif args.action == "unset":
            emit({"key": args.key, "removed": inventory.unset(args.key)})
        return 0

    if args.group == "catalog":
        catalog = Catalog(layout)
        if args.action == "apps":
            emit([a.as_dict() for a in catalog.apps(include_hidden=args.all)])
        elif args.action == "roles":
            emit([r.as_dict() for r in catalog.saltbox_roles])
        elif args.action == "profiles":
            emit(catalog.profiles)
        elif args.action == "categories":
            emit(catalog.categories())
        elif args.action == "fields":
            defaults = catalog.defaults(args.role, args.repo)
            if defaults is None:
                emit({"error": f"no defaults for role {args.role}"})
                return 1
            data = defaults.as_dict()
            if not args.all:
                data["fields"] = [f.as_dict() for f in defaults.visible()]
            emit(data)
        return 0

    if args.group == "state":
        if args.action == "facts":
            if args.role:
                facts = read_role_facts(layout, args.role)
                if not args.secrets:
                    from .state.facts import redact_value

                    facts = {
                        i: {k: redact_value(k, v) for k, v in vals.items()}
                        for i, vals in facts.items()
                    }
                emit(facts)
            else:
                emit(
                    {
                        "roles": list_fact_roles(layout),
                        "facts": read_all_facts(layout, redact=not args.secrets),
                    }
                )
        elif args.action == "ports":
            emit(read_port_assignments(layout))
        elif args.action == "mounts":
            emit(mounts())
        elif args.action == "disks":
            emit(disk_usage())
        elif args.action == "units":
            emit(systemd_units())
        elif args.action == "containers":
            try:
                emit(list_containers())
            except RuntimeError as error:
                emit({"error": str(error)})
                return 1
        elif args.action == "tags":
            emit(cached_tags(layout))
        elif args.action == "motd":
            emit(read_motd_services(layout, redact=not args.secrets))
        elif args.action == "host":
            emit(
                {
                    "reboot_required": reboot_required(),
                    "disks": disk_usage(),
                    "mounts": mounts(),
                    "units": systemd_units(),
                }
            )
        return 0

    if args.group == "run":
        runner = SbRunner(layout)
        if args.action == "install":
            tags = [t for t in args.tags.split(",") if t]
            skip = [t for t in args.skip_tags.split(",") if t]
            command = runner.install_command(
                tags,
                skip_tags=skip,
                extra_vars=args.extra_vars,
                verbosity=args.verbose,
                no_cache=args.no_cache,
            )
            if args.dry_run:
                emit({"command": command})
                return 0
            job = runner.run(
                command,
                kind="install",
                tags=tags,
                on_line=lambda line: print(line, file=sys.stderr),
            )
            emit(job.as_dict())
            return 0 if job.status == "succeeded" else 1
        if args.action == "update":
            command = runner.update_command()
            if args.dry_run:
                emit({"command": command})
                return 0
            job = runner.run(
                command, kind="update", on_line=lambda line: print(line, file=sys.stderr)
            )
            emit(job.as_dict())
            return 0 if job.status == "succeeded" else 1
        if args.action == "jobs":
            emit([j.as_dict() for j in runner.jobs()])
        elif args.action == "log":
            sys.stdout.write(runner.log(args.job_id))
        elif args.action == "status":
            emit({"running": runner.is_locked()})
        return 0

    if args.group == "install":
        from .installer import InstallerSession, run_preflight
        from .installer.preflight import summarize

        session = InstallerSession(layout)
        if args.action == "preflight":
            checks = run_preflight(layout)
            emit({"summary": summarize(checks), "checks": [c.as_dict() for c in checks]})
            return 3 if any(c.blocking for c in checks) else 0
        if args.action == "plan":
            emit(
                {
                    "path": str(session.plan_path),
                    "resumable": session.resumable,
                    "plan": session.plan.redacted(),
                }
            )
        elif args.action == "discard":
            session.discard()
            emit({"discarded": True})
        elif args.action == "apply":
            touched = session.apply_config()
            payload = {"written": touched}
            if args.validate:
                results = session.validate()
                payload["issues"] = {
                    n: [i.as_dict() for i in found] for n, found in results.items()
                }
                payload["ok"] = not session.has_errors(results)
            emit(payload)
        elif args.action == "tags":
            emit({"tags": session.plan.install_tags()})
        return 0

    if args.group == "tui":
        from .tui.app import run_installer

        run_installer(layout)
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


def _daemon(args: argparse.Namespace, layout: Layout) -> int:
    from pathlib import Path

    from .daemon.app import ensure_token, read_token
    from .daemon.install import (
        UNIT_NAME,
        enable_web,
        install_unit,
        systemctl,
        systemd_unit,
        url_for,
        write_route,
    )

    if args.action == "unit":
        print(systemd_unit(), end="")
        return 0
    if args.action == "url":
        emit({"url": url_for(layout)})
        return 0
    if args.action == "token":
        token = read_token(layout)
        emit({"token": token, "path": str(layout.state_dir / "api-token")})
        return 0 if token else 1
    if args.action == "status":
        code, output = systemctl("status", "--no-pager", UNIT_NAME)
        emit({"active": code == 0, "output": output})
        return 0
    if args.action == "enable":
        web = Path(args.web) if args.web else None
        emit(enable_web(layout, subdomain=args.subdomain, web=web, start=not args.no_start))
        return 0
    if args.action == "route":
        token = ensure_token(layout)
        traefik_dir = Path(args.traefik_dir) if args.traefik_dir else None
        path = write_route(layout, token, subdomain=args.subdomain, traefik_dir=traefik_dir)
        emit({"route": str(path), "url": url_for(layout, args.subdomain)})
        return 0
    if args.action == "install":
        ensure_token(layout)
        web = Path(args.web) if args.web else None
        unit = install_unit(web=web)
        steps = {"unit": str(unit)}
        code, output = systemctl("daemon-reload")
        steps["daemon-reload"] = output or ("ok" if code == 0 else f"exit {code}")
        if not args.no_start:
            code, output = systemctl("enable", "--now", UNIT_NAME)
            steps["enable"] = output or ("ok" if code == 0 else f"exit {code}")
        emit(steps)
        return 0
    return 1
