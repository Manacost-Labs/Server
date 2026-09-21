"""Optional local ai-memory integration; selected projects, no model credentials."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_CONFIG = Path.home() / ".config/codex-context-economy/projects.json"


def load_config(path=None):
    path = Path(path or os.environ.get("CONTEXT_ECONOMY_PROJECTS", DEFAULT_CONFIG))
    if not path.exists():
        return None
    config = json.loads(path.read_text())
    url = urlsplit(config["server_url"])
    if (url.scheme != "http" or url.hostname != "127.0.0.1" or url.username or url.password
            or url.path not in ("", "/") or url.query or url.fragment):
        raise ValueError("ai-memory integration requires an explicit loopback HTTP server")
    if not config.get("projects"):
        raise ValueError("No ai-memory projects configured")
    return config


def select_project(config, root):
    root = Path(root).resolve()
    projects = config["projects"]
    for item in sorted(projects, key=lambda p: len(p["root"]), reverse=True):
        canonical = Path(item["root"]).resolve()
        if root == canonical or root.is_relative_to(canonical):
            return item
    # Linked worktrees inherit identity from the selected repository, not a basename.
    probe = subprocess.run(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                           capture_output=True, text=True, timeout=2)
    if probe.returncode == 0:
        common = Path(probe.stdout.strip()).resolve()
        for item in projects:
            if common == Path(item["git_common_dir"]).resolve():
                return item
    return None


def environment(config):
    # Explicit allowlist: neither service nor helper inherits an LLM provider/key.
    result = {key: os.environ[key] for key in ("HOME", "LANG") if key in os.environ}
    result.update(PATH="/usr/bin:/bin", RUST_LOG="error",
                  AI_MEMORY_SERVER_URL=config["server_url"],
                  AI_MEMORY_DATA_DIR=config["data_dir"],
                  AI_MEMORY_AUTH_TOKEN=Path(config["token_file"]).read_text().strip(),
                  AI_MEMORY_EMBEDDING_PROVIDER="none",
                  AI_MEMORY_BACKFILL_ON_START="false", AI_MEMORY_RUN_AUTOWIRE="false")
    return result


class Client:
    def __init__(self, config, project):
        self.config, self.project = config, project

    def call(self, command, *args, body=None):
        argv = [self.config["binary"], command, "--workspace", "manacost",
                "--project", self.project["id"], *args]
        result = subprocess.run(argv, input=body, capture_output=True, text=True,
                                timeout=2, env=environment(self.config), cwd=self.project["root"])
        if result.returncode:
            raise ValueError("ai-memory request failed; inspect the local service status")
        if len(result.stdout.encode()) > 1024 * 1024:
            raise ValueError("ai-memory response exceeds the adapter budget")
        return result.stdout

    def write(self, path, text, title):
        self.call("write-page", "--path", path, "--body", "-", "--title", title, body=text)

    def search(self, query, limit=10):
        return json.loads(self.call("search", query, "--limit", str(limit), "--json"))

    def read(self, path):
        return json.loads(self.call("read-page", "--path", path, "--json"))


def client_for(root):
    config = load_config()
    project = select_project(config, root) if config else None
    return Client(config, project) if project else None


def mirror(store, identifier):
    """Local commit succeeds even when the optional service is unavailable."""
    from . import memory
    try:
        client = client_for(store.root)
        if client is None:
            return "local"
        note = memory.inspect(store, identifier)
        payload = {key: note[key] for key in ("id", "text", "evidence", "sources", "created", "expires")}
        client.write(f"verified/{identifier}.md", json.dumps(payload, ensure_ascii=False), note["text"][:100])
        return "local+ai-memory"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return "local; ai-memory unavailable"


def search(store, query, limit=20):
    """Only explicit verified notes qualify; revalidate against this checkout."""
    from . import memory
    local = memory.search(store, query, limit)
    seen = {note["id"] for note in local}
    if len(local) >= limit or not query.strip():
        return local
    try:
        client = client_for(store.root)
        if client is None:
            return local
        deadline = time.monotonic() + 3
        hits = client.search(query, min(limit, 5))
        for hit in hits:
            if time.monotonic() >= deadline or len(local) >= limit:
                break
            path = hit["path"]
            if not path.startswith("verified/") or ".." in path.split("/"):
                continue
            page = client.read(path)
            if page.get("workspace") != "manacost" or page.get("project") != client.project["id"]:
                continue
            row = json.loads(page["body"])
            identifier = row["id"]
            if path != f"verified/{identifier}.md" or identifier in seen:
                continue
            if (not isinstance(row["text"], str) or not 0 < len(row["text"]) <= 8000
                    or not isinstance(row["evidence"], str) or not 0 < len(row["evidence"]) <= 2000
                    or not isinstance(row["sources"], dict) or len(row["sources"]) > 20
                    or not 0 < row["expires"] - row["created"] <= 365 * 86400):
                continue
            row["sources"] = json.dumps(row["sources"])
            note = memory._note(store, row)
            if note["fresh"]:
                local.append(note)
                seen.add(identifier)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("ai-memory unavailable or invalid response; using local verified notes", file=sys.stderr)
    return local
