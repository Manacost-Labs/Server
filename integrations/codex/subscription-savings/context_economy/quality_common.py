"""Shared bounded inputs, versioned caches and host-wide resource coordination."""

import contextlib
import fcntl
import json
import os
import time
from pathlib import Path

from .common import digest, encode, private_dir, read_source

VERSION = "quality-v2"
SKIP = {".git", ".next", "node_modules", "vendor", "dist", "build", "coverage",
        "secrets", "sessions", "backups", "uploads", "__pycache__"}
CODE = {".py", ".go", ".php", ".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".svg"}


def sources(root, selected, maximum=200, allow_empty=False):
    """Expand only explicitly selected, code-only paths; reject overflow, never truncate."""
    if not selected or len(selected) > 20:
        raise ValueError("Select 1–20 source paths")
    root = Path(root).resolve()
    result = {}
    visited = 0
    for spec in selected:
        path = Path(spec)
        if path.is_absolute() or ".." in path.parts or path.as_posix() in {".", ""}:
            raise ValueError("Select bounded project-relative files/directories, not the whole project")
        current = root
        for part in path.parts:
            current /= part
            if current.is_symlink() or part in SKIP or part.startswith(".env"):
                raise ValueError("Protected or symlink source")
        target = root / path
        if not target.exists():
            raise ValueError(f"Missing selected path: {spec}")
        candidates = [target] if target.is_file() else []
        if target.is_dir():
            for directory, dirs, files in os.walk(target, followlinks=False):
                visited += 1
                if visited > 500:
                    raise ValueError("Directory budget exceeded; narrow selected paths")
                dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith(".")
                                 and not (Path(directory) / d).is_symlink())
                candidates.extend(Path(directory) / name for name in sorted(files)
                                  if Path(name).suffix in CODE and not name.startswith("."))
                if len(candidates) > maximum:
                    raise ValueError("Source budget exceeded; narrow selected paths")
        for candidate in candidates:
            if candidate.suffix not in CODE:
                continue
            rel = candidate.relative_to(root).as_posix()
            result[rel] = read_source(root, rel)
            if len(result) > maximum or sum(len(x["text"].encode()) for x in result.values()) > 4_000_000:
                raise ValueError("Source budget exceeded (200 files / 4 MB)")
    if not result and not allow_empty:
        raise ValueError("No supported source files in selected paths")
    return result


def cache_get(store, namespace, key, ttl=86400):
    _cache_tables(store)
    row = store.db.execute("SELECT created,value FROM quality_cache WHERE namespace=? AND key=?",
                           (namespace, digest(encode([VERSION, key]).encode()))).fetchone()
    now = time.time()
    age = now - row["created"] if row else None
    event = "misses" if row is None else "hits" if 0 <= age < ttl else "expired"
    _cache_count(store, namespace, event, now)
    store.db.commit()
    return json.loads(row["value"]) if event == "hits" else None


def cache_put(store, namespace, key, value):
    _cache_tables(store)
    now = time.time()
    store.db.execute("INSERT OR REPLACE INTO quality_cache VALUES(?,?,?,?)",
                     (namespace, digest(encode([VERSION, key]).encode()), now, encode(value)))
    _cache_count(store, namespace, "writes", now)
    # Count actual evictions by namespace without retaining keys or query text.
    overflow = store.db.execute("SELECT rowid,namespace FROM quality_cache "
                                "ORDER BY created DESC,rowid DESC LIMIT -1 OFFSET 1000").fetchall()
    for row in overflow:
        store.db.execute("DELETE FROM quality_cache WHERE rowid=?", (row["rowid"],))
        _cache_count(store, row["namespace"], "evictions", now)
    store.db.commit()


def _cache_tables(store):
    store.db.execute("CREATE TABLE IF NOT EXISTS quality_cache "
                     "(namespace TEXT, key TEXT, created REAL, value TEXT, PRIMARY KEY(namespace,key))")
    store.db.execute("CREATE TABLE IF NOT EXISTS quality_cache_counters "
                     "(namespace TEXT, event TEXT, count INTEGER NOT NULL, PRIMARY KEY(namespace,event))")
    store.db.execute("CREATE TABLE IF NOT EXISTS quality_cache_daily "
                     "(namespace TEXT, day INTEGER, event TEXT, count INTEGER NOT NULL, "
                     "PRIMARY KEY(namespace,day,event))")
    store.db.execute("CREATE INDEX IF NOT EXISTS quality_cache_daily_day ON quality_cache_daily(day)")


def _cache_count(store, namespace, event, now):
    store.db.execute("INSERT INTO quality_cache_counters VALUES(?,?,1) "
                     "ON CONFLICT(namespace,event) DO UPDATE SET count=count+1", (namespace, event))
    day = int(now // 86400)
    store.db.execute("INSERT INTO quality_cache_daily VALUES(?,?,?,1) "
                     "ON CONFLICT(namespace,day,event) DO UPDATE SET count=count+1", (namespace, day, event))
    store.db.execute("DELETE FROM quality_cache_daily WHERE day<?", (day - 29,))


def cache_stats(store, days=7):
    """Aggregate cache activity without exposing source, query or cache keys."""
    if type(days) is not int or not 1 <= days <= 30:
        raise ValueError("Cache history requires 1–30 days")
    _cache_tables(store)
    names = {}
    for row in store.db.execute("SELECT namespace,event,count FROM quality_cache_counters"):
        names.setdefault(row["namespace"], {name: 0 for name in
                         ("hits", "misses", "expired", "writes", "evictions", "entries")})[row["event"]] = row["count"]
    for row in store.db.execute("SELECT namespace,COUNT(*) AS count FROM quality_cache GROUP BY namespace"):
        names.setdefault(row["namespace"], {name: 0 for name in
                         ("hits", "misses", "expired", "writes", "evictions", "entries")})["entries"] = row["count"]
    today = int(time.time() // 86400)
    daily = {}
    for row in store.db.execute("SELECT namespace,day,event,count FROM quality_cache_daily "
                                "WHERE day BETWEEN ? AND ? ORDER BY namespace,day,event", (today - days + 1, today)):
        date = time.strftime("%Y-%m-%d", time.gmtime(row["day"] * 86400))
        rows = daily.setdefault(row["namespace"], {})
        bucket = rows.setdefault(date, {"date_utc": date, **{event: 0 for event in
                                      ("hits", "misses", "expired", "writes", "evictions")}})
        bucket[row["event"]] = row["count"]
    return {"limit": 1000, "ttl_seconds": 86400, "namespaces": names, "days": days,
            "daily": {namespace: list(rows.values()) for namespace, rows in daily.items()}}


@contextlib.contextmanager
def resource_lock(store, name="heavy"):
    if name not in {"heavy", "index", "network"}:
        raise ValueError("Unknown resource lock")
    # Heavy indexing and benchmarks deliberately share one host/user lock.
    name = "heavy" if name in {"heavy", "index"} else name
    directory = private_dir(store.directory.parent / "quality-locks")
    fd = os.open(directory / (name + ".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(f"Resource busy: {name}; retry after the active job finishes") from exc
        yield
    finally:
        os.close(fd)


def load_config(root, name=".ai/manacost-quality.json"):
    data = json.loads(read_source(root, name)["text"])
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Quality configuration must be a version 1 object")
    return data


def load_profile(name):
    if name not in {"hearthpulse", "hs-manacost", "nextjs", "go", "wordpress"}:
        raise ValueError("Unknown bundled project/stack profile")
    path = Path(__file__).resolve().parents[1] / "quality/profiles" / (name + ".json")
    return json.loads(path.read_text())
