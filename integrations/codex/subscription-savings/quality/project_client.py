#!/usr/bin/env python3
"""Small project-owned client for the versioned server quality release.

Canonical template: integrations/codex/subscription-savings/quality/project_client.py.
Project CI validates its own native check commands without needing API credentials.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def project_file(root, path):
    root = Path(root).resolve()
    target = (root / path).resolve()
    if Path(path).is_absolute() or not target.is_relative_to(root) or not target.is_file():
        raise ValueError(f"Expected a project-local file: {path}")
    return target


def validate(root, path):
    config = json.loads(project_file(root, path).read_text())
    scripts = json.loads((root / "package.json").read_text()).get("scripts", {}) if (root / "package.json").exists() else {}
    makefile = (root / "Makefile").read_text() if (root / "Makefile").exists() else ""
    targets = set(re.findall(r"^([\w-]+):", makefile, re.M))
    if config.get("stack") not in {"wordpress", "nextjs", "go"} or not config.get("checks"):
        raise ValueError("Quality config requires a supported stack and checks")
    identifiers = set()
    for check in config["checks"]:
        if set(check) - {"id", "argv", "tier", "paths", "timeout", "network", "family"}:
            raise ValueError("Unknown quality check field")
        if check.get("tier", "fast") not in {"fast", "medium", "heavy"}:
            raise ValueError("Unknown quality check tier")
        if type(check.get("network", False)) is not bool:
            raise ValueError("Check network flag must be boolean")
        identifier, argv = check.get("id"), check.get("argv")
        if not identifier or identifier in identifiers or not isinstance(argv, list) or not argv:
            raise ValueError("Invalid or duplicate quality check")
        identifiers.add(identifier)
        if any(not isinstance(arg, str) or not arg for arg in argv):
            raise ValueError("Check argv must contain explicit nonempty strings")
        if argv[0] == "make" and (len(argv) < 2 or argv[1] not in targets):
            raise ValueError(f"Missing native make target for {identifier}")
        if argv[:2] == ["npm", "run"] and (len(argv) < 3 or argv[2] not in scripts):
            raise ValueError(f"Missing native npm script for {identifier}")
    registry = config.get("design", {}).get("registry", [])
    if isinstance(registry, str):
        registry = json.loads(project_file(root, registry).read_text())["components"]
    for component in registry:
        path = component.get("source", component.get("path"))
        if path:
            project_file(root, path)
    return {"ok": True, "checks": sorted(identifiers), "stack": config["stack"]}


def main(root):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/quality-guard.json")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--risk", choices=("low", "medium", "high", "critical"), default="low")
    parser.add_argument("--family", choices=("all", "engineering", "design"), default="all")
    parser.add_argument("--task-type", default="implementation")
    parser.add_argument("--changed", action="append", default=[])
    parser.add_argument("--allow-heavy", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    if Path(args.config).is_absolute() or ".." in Path(args.config).parts:
        parser.error("Config must be project-relative")
    try:
        result = validate(root, args.config)
        if args.check_config:
            print(json.dumps(result))
            return 0
        release = Path(os.environ.get("MANACOST_QUALITY_ROOT",
                                      str(Path.home() / ".local/share/codex-context-economy/current"))).resolve()
        entry = release / "context_economy.py"
        python = release / ".venv/bin/python"
        if not entry.is_file() or not python.is_file():
            raise ValueError("Install the versioned quality release with its venv, or select MANACOST_QUALITY_ROOT")
        command = [str(python), str(entry), "--project", str(root), "quality-plan" if args.plan else "quality-verify",
                   "--config", args.config, "--risk", args.risk, "--task-type", args.task_type]
        if args.family != "all":
            command.extend(["--family", args.family])
        for path in args.changed or [args.config]:
            command.extend(["--changed", path])
        for name in ("allow_heavy", "allow_network"):
            if getattr(args, name) and not args.plan:
                command.append("--" + name.replace("_", "-"))
        env = {**os.environ, "PATH": str(release / "quality/node_modules/.bin") + os.pathsep + os.environ.get("PATH", "")}
        # Operator-selected local toolchain, not web input; explicit argv and no shell.
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args
        return subprocess.run(command, cwd=root, env=env, check=False).returncode
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(Path(__file__).resolve().parents[2]))
