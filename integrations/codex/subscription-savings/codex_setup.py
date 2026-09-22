"""Explicit, owned-file Codex setup; never edits a home merely by importing."""
import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent
VERSION = "0.153.0"
PROFILES = {"minimal": [], "code": ["codegraph"], "web": ["chrome-devtools"],
            "research": ["context7", "openaiDeveloperDocs"], "github": ["github"],
            "infra": ["cloudflare", "ovhcloud"], "typeui": []}
MANIFEST = "economy-setup.json"


def cli_check():
    if sys.version_info < (3, 11):
        raise ValueError("Python 3.11+ is required")
    for command in ("bash", "readlink"):
        if not shutil.which(command):
            raise ValueError(f"Required local dependency missing: {command}")
    if not shutil.which("codex"):
        raise ValueError("codex is missing; install the supported CLI before setup")
    result = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=10, check=True)
    if result.stdout.strip() != "codex-cli " + VERSION:
        raise ValueError(f"Unsupported Codex version; tested {VERSION}, found {result.stdout.strip()!r}. "
                         "Validate the new release before updating the compatibility pin.")
    help_text = subprocess.run(["codex", "--help"], capture_output=True, text=True, timeout=10, check=True).stdout
    if "<CONFIG_PROFILE_V2>" not in help_text or "<name>.config.toml" not in help_text:
        raise ValueError("Codex does not advertise the required V2 file profiles")


def rendered():
    config = (ROOT / "config.example.toml").read_text()
    # Substitute a shell-quoted argv, then TOML-quote the whole command string.
    config = config.replace('"@OBSERVATION_COMMAND@"', json.dumps(shlex.join([sys.executable, str(ROOT / "observation_pack.py")])))
    config = config.replace('"@COMPACTION_COMMAND@"', json.dumps(shlex.join(["bash", str(ROOT / "bin/compact-plus-hook"), "precompact-state-summary.sh"])))
    for name in ("precompact-transcript-backup.sh", "compaction-recovery.sh",
                 "sessionstart-compaction-recovery.sh", "sessionstart-export-session-id.sh",
                 "userpromptsubmit-compaction-recovery.sh", "userpromptsubmit-compact-plus-reminder.sh"):
        config = config.replace(json.dumps("@" + name + "@"),
                                json.dumps(shlex.join(["bash", str(ROOT / "bin/compact-plus-hook"), name])))
    files = {"config.toml": config.encode()}
    for profile in PROFILES:
        files[profile + ".config.toml"] = (ROOT / "profiles" / (profile + ".config.toml")).read_bytes()
    return files


def digest(data):
    return hashlib.sha256(data).hexdigest()


def ownership(home):
    if home.is_symlink() or any(p.is_symlink() for p in home.parents):
        raise ValueError("CODEX_HOME and its ancestors must not be symlinks")
    manifest = home / MANIFEST
    if manifest.is_symlink():
        raise ValueError("Refusing symlink ownership manifest")
    if manifest.exists():
        record = json.loads(manifest.read_text())
        expected = {"config.toml", *(p + ".config.toml" for p in PROFILES)}
        if record.get("schema") != 1 or set(record.get("files", {})) != expected:
            raise ValueError("Unrecognized setup manifest; manual migration required")
        for name, checksum in record["files"].items():
            path = home / name
            if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != checksum:
                raise ValueError(f"User-modified or missing managed file: {name}; refusing overwrite")
        return record
    for name in rendered():
        path = home / name
        if path.exists() or path.is_symlink():
            raise ValueError(f"Unknown user configuration: {path}; use a fresh CODEX_HOME or migrate manually")
    return None


def effective(home, profile):
    if profile not in PROFILES:
        raise ValueError("Unknown profile: " + profile)
    path = home / (profile + ".config.toml")
    if not path.is_file():
        raise ValueError(f"Missing profile {path}; run codex_setup.py --dry-run first")
    base = tomllib.loads((home / "config.toml").read_text())
    overlay = tomllib.loads(path.read_text())
    if "mcp_servers" not in overlay or set(overlay) - {"mcp_servers", "plugins"}:
        raise ValueError("Incompatible profile format: expected explicit MCP and optional plugin enabled booleans")
    for section in ("mcp_servers", "plugins"):
        values = overlay.get(section, {})
        if not isinstance(values, dict) or any(not isinstance(v, dict) or set(v) != {"enabled"} or
                                               type(v["enabled"]) is not bool for v in values.values()):
            raise ValueError(f"Incompatible {section} profile format: only enabled booleans are supported")
    servers = {name: dict(value) for name, value in base.get("mcp_servers", {}).items()}
    for name, value in overlay.get("mcp_servers", {}).items():
        servers.setdefault(name, {}).update(value)
    active = {name for name, value in servers.items() if value.get("enabled", True)}
    if active != set(PROFILES[profile]):
        raise ValueError(f"Incompatible {profile} MCP set: {sorted(active)}; expected {PROFILES[profile]}")
    return servers


def dependencies(servers):
    missing = []
    for name, value in servers.items():
        if value.get("enabled", True) and "command" in value and not shutil.which(value["command"]):
            missing.append(f"{name}: {value['command']}")
    return missing


def validate_runtime(home, profile):
    # app-server accepts --strict-config but rejects -p in 0.153.0. Strictly
    # validate the base; effective() restricts overlays to MCP/plugin booleans.
    effective(home, profile)
    subprocess.run(["codex", "app-server", "--strict-config"], input="", cwd=home,
                   env={**os.environ, "CODEX_HOME": str(home)}, capture_output=True, text=True,
                   timeout=20, check=True)
    return inspect_runtime(home, profile, home)


def inspect_runtime(home, profile, cwd):
    # This local command parses/merges config without starting a model or MCP server.
    result = subprocess.run(["codex", "-p", profile, "mcp", "list", "--json"], cwd=cwd,
                            env={**os.environ, "CODEX_HOME": str(home)},
                            capture_output=True, text=True, timeout=20, check=True)
    servers = json.loads(result.stdout)
    active = {s["name"] for s in servers if s["enabled"]}
    optional = plugin_mcp(home, profile)
    if active - optional != set(PROFILES[profile]):
        raise ValueError(f"CLI profile merge disagrees for {profile}: {sorted(active)}")
    return servers


def plugin_mcp(home, profile):
    # A known installed plugin can contribute an MCP outside mcp_servers.
    # Never grant this exception to minimal or to arbitrary plugin/server names.
    if profile != "typeui":
        return set()
    base = tomllib.loads((home / "config.toml").read_text()).get("plugins", {})
    overlay = tomllib.loads((home / (profile + ".config.toml")).read_text()).get("plugins", {})
    settings = dict(base.get("typeui@bergside", {}))
    settings.update(overlay.get("typeui@bergside", {}))
    return {"typeui"} if settings.get("enabled") is True else set()


def atomic(path, data):
    fd, temporary = tempfile.mkstemp(prefix=".economy-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install(home, files, previous):
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Recheck just before mutation. A lock serializes cooperating installer runs.
    import fcntl
    lock_fd = os.open(home / ".economy-setup.lock", os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if ownership(home) != previous:
            raise ValueError("Configuration changed during setup; retry")
        if previous and all(previous["files"][n] == digest(d) for n, d in files.items()):
            return {"status": "unchanged", "backup": None}
        backup = home / ("economy-backup-" + str(time.time_ns()))
        backup.mkdir(mode=0o700)
        names = [*files, MANIFEST]
        before = {n: (home / n).read_bytes() if (home / n).exists() else None for n in names}
        for name, data in before.items():
            if data is not None:
                atomic(backup / name, data)
        atomic(backup / "restore.json", json.dumps({"existed": [n for n, d in before.items() if d is not None],
                                                   "managed_paths": names}).encode())
        try:
            for name, data in files.items():
                atomic(home / name, data)
            atomic(home / MANIFEST, json.dumps({"schema": 1, "codex_version": VERSION,
                                               "files": {n: digest(d) for n, d in files.items()}}, indent=2).encode())
        except BaseException:
            for name, data in before.items():
                if data is None:
                    (home / name).unlink(missing_ok=True)
                else:
                    atomic(home / name, data)
            raise
        return {"status": "installed", "backup": str(backup)}


def launch(argv):
    if not argv:
        raise ValueError("Usage: codex-context PROFILE [codex arguments]")
    profile, *args = argv
    cli_check()
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).absolute()
    servers = effective(home, profile)
    missing = dependencies(servers)
    if missing:
        raise ValueError("Missing profile tools: " + "; ".join(missing))
    # Include actual project/admin layers at the launch cwd, not just the
    # managed base. No MCP servers or models are started by mcp list.
    runtime = inspect_runtime(home, profile, Path.cwd())
    missing_plugin = plugin_mcp(home, profile) - {s["name"] for s in runtime if s["enabled"]}
    if missing_plugin:
        raise ValueError("Missing installed plugin MCP: " + ", ".join(sorted(missing_plugin)))
    for server in runtime:
        transport = server.get("transport", {})
        if server["enabled"] and transport.get("type") == "stdio" and not shutil.which(transport["command"]):
            raise ValueError("Missing effective profile tool: " + server["name"])
    # Profile overrides can invalidate the guarantees just checked.
    if any(a in ("-p", "--profile", "-c", "--config", "--enable", "--disable") or
           a.startswith(("--profile=", "--config=", "--enable=", "--disable=", "-c", "-p")) for a in args):
        raise ValueError("Configuration overrides bypass profile checks; edit and verify the profile explicitly")
    os.execvp("codex", ["codex", "-p", profile, *args])


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "launch":
        launch(sys.argv[2:])
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ("dry-run", "verify", "install"):
        modes.add_argument("--" + mode, action="store_true")
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    args = parser.parse_args()
    cli_check()
    home = args.codex_home.absolute()
    previous = ownership(home)
    files = rendered()
    # Never run Codex against the operator's home during planning/verification.
    with tempfile.TemporaryDirectory(prefix="codex-setup-") as temporary:
        stage = Path(temporary)
        if args.verify:
            if previous is None:
                raise ValueError("No managed installation to verify")
            files = {n: (home / n).read_bytes() for n in files}
        for name, data in files.items():
            (stage / name).write_bytes(data)
        optional = {}
        for profile in PROFILES:
            servers = effective(stage, profile)
            validate_runtime(stage, profile)
            optional[profile] = dependencies(servers)
    result = install(home, files, previous) if args.install else {"status": "verified" if args.verify else "dry-run"}
    result.update(codex_version=VERSION, target=str(home), files=sorted(files), missing_optional_tools=optional,
                  python_version=".".join(map(str, sys.version_info[:3])),
                  compact_plus_plugin_present=(home / "plugins/compact-plus/hooks/precompact-state-summary.sh").is_file(),
                  hooks="Commands must be reviewed/trusted locally with /hooks; no trust state is copied")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"codex-setup: {exc}", file=sys.stderr)
        raise SystemExit(2)
