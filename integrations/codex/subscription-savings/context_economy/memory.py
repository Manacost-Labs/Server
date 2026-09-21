"""Evidence-backed notes, FTS retrieval, content and time invalidation."""

import json
import math
import re
import time

from .common import digest, encode, read_source


def add(store, text, evidence, files, ttl_days=30):
    if not isinstance(text, str) or not text.strip() or len(text) > 8000:
        raise ValueError("Note text must contain 1–8000 characters")
    if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 2000:
        raise ValueError("Evidence must contain 1–2000 characters")
    if not math.isfinite(ttl_days) or not 0 < ttl_days <= 365:
        raise ValueError("TTL must be greater than zero and at most 365 days")
    if len(files) > 20:
        raise ValueError("At most 20 explicit dependencies per note")
    sources = {}
    for spec in files:
        source = read_source(store.root, spec)
        sources[source["path"]] = source["sha256"]
    # A new verification after TTL expiry gets a new record; no silent refresh.
    fingerprint = digest(encode([text, evidence, sources]).encode())
    existing = store.db.execute("SELECT id FROM notes WHERE id LIKE ? AND expires > ?",
                                (fingerprint + "%", time.time())).fetchone()
    if existing:
        return existing["id"]
    now = time.time()
    identifier = f"{fingerprint}-{time.time_ns()}"
    with store.db:
        store.db.execute("INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?)",
                         (identifier, text, evidence, encode(sources), now, now + ttl_days * 86400))
        store.db.execute("INSERT INTO notes_fts VALUES (?, ?, ?)", (identifier, text, evidence))
    return identifier


def _note(store, row):
    note = dict(row)
    note["sources"] = json.loads(note["sources"])
    reasons = []
    if note["expires"] <= time.time():
        reasons.append("expired")
    for path, expected in note["sources"].items():
        try:
            if read_source(store.root, path)["sha256"] != expected:
                reasons.append(f"changed: {path}")
        except ValueError:
            reasons.append(f"unavailable: {path}")
    note["fresh"] = not reasons
    note["stale_reasons"] = reasons
    return note


def inspect(store, identifier):
    row = store.db.execute("SELECT * FROM notes WHERE id = ?", (identifier,)).fetchone()
    if row is None:
        raise ValueError("Unknown note id")
    return _note(store, row)


def search(store, query, limit=20):
    if not 1 <= limit <= 50:
        raise ValueError("Search limit must be between 1 and 50")
    words = list(dict.fromkeys(re.findall(r"\w+", query, re.UNICODE)))[:32]
    if not words:
        return []
    expression = " OR ".join('"' + word + '"' for word in words)
    # Bound freshness checks even when many old records match; callers can refine query.
    rows = store.db.execute("""
        SELECT notes.* FROM notes_fts JOIN notes ON notes.id = notes_fts.id
        WHERE notes_fts MATCH ? AND notes.expires > ? ORDER BY rank LIMIT 200
    """, (expression, time.time()))
    result = []
    for row in rows:
        note = _note(store, row)
        if note["fresh"]:
            result.append(note)
            if len(result) == limit:
                break
    return result
