"""Bounded source reads and project-isolated private storage."""

import hashlib
import json
import os
import re
import sqlite3
import stat
from pathlib import Path

MAX_SOURCE_BYTES = 1024 * 1024


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def read_source(root, spec):
    match = re.fullmatch(r"(.+?):(\d+):(\d+)", spec)
    name = match[1] if match else spec
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Sources must be project-relative paths without '..'")
    for part in relative.parts:
        lower = part.lower()
        if (lower.startswith((".env", "credentials", "id_rsa", "id_ed25519"))
                or lower in {".git", ".ssh", "secrets", "sessions"}
                or lower.endswith((".pem", ".key", ".p12", ".db", ".sqlite"))):
            raise ValueError("Sensitive source path is not allowed")
    root = Path(root).resolve()
    path = root / relative
    # Reject all symlink components, including aliases to otherwise permitted files.
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink sources are not allowed")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Source escapes project")
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError("Source must be a regular file")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Source must be a regular file")
            raw = stream.read(MAX_SOURCE_BYTES + 1)
    except OSError as exc:
        raise ValueError(f"Cannot read selected source: {spec}") from exc
    if len(raw) > MAX_SOURCE_BYTES or b"\0" in raw:
        raise ValueError("Source is binary or exceeds the 1 MiB read limit; select a smaller artifact")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Source must be UTF-8 text") from exc
    if match:
        start, end = int(match[2]), int(match[3])
        lines = text.splitlines(keepends=True)
        if not 1 <= start <= end <= len(lines):
            raise ValueError("Invalid source line range")
        text = "".join(lines[start - 1:end])
    return {"source": spec, "path": relative.as_posix(), "sha256": digest(raw), "text": text}


def private_dir(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("Symlink state directories are not allowed")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_uid != os.getuid():
        raise ValueError("State directory must belong to the current user")
    path.chmod(0o700)
    return path


class Store:
    def __init__(self, root, state_dir=None):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Project must be a directory")
        base = Path(state_dir) if state_dir else Path.home() / ".local/state/codex-context-economy"
        self.directory = private_dir(base / digest(str(self.root).encode())[:24])
        db = self.directory / "state.sqlite3"
        fd = os.open(db, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise ValueError("Invalid state database")
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        self.db = sqlite3.connect(db, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY, text TEXT NOT NULL, evidence TEXT NOT NULL,
                sources TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(id UNINDEXED, text, evidence);
            CREATE TABLE IF NOT EXISTS api_cache (key TEXT PRIMARY KEY, created REAL, response TEXT);
            CREATE TABLE IF NOT EXISTS api_calls (created REAL, usage TEXT);
            CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        """)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
