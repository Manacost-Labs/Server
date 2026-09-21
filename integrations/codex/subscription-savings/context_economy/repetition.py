"""Advisory repetition hints; never suppress output, skip checks or switch models."""

import time

from . import meter
from .common import digest, encode


def observe(store, kind, identity, version, hypothesis=""):
    if len(hypothesis) > 1000:
        raise ValueError("Hypothesis must be at most 1000 characters")
    store.db.execute("""CREATE TABLE IF NOT EXISTS repetition_events (
        id INTEGER PRIMARY KEY, scope TEXT, kind TEXT, fingerprint TEXT, created REAL)""")
    scope = meter.active_id(store) or "unscoped"
    fingerprint = digest(encode([identity, version, hypothesis]).encode())
    now = time.time()
    with store.db:
        store.db.execute("DELETE FROM repetition_events WHERE created < ?", (now - 3600,))
        store.db.execute("INSERT INTO repetition_events VALUES(NULL,?,?,?,?)", (scope, kind, fingerprint, now))
        count = store.db.execute("SELECT COUNT(*) FROM repetition_events WHERE scope=? AND kind=? AND fingerprint=?",
                                 (scope, kind, fingerprint)).fetchone()[0]
    if count < 2:
        return None
    return {"kind": kind, "observations": count,
            "hint": "Same source version was read again; reuse the earlier result if still applicable."
            if kind == "read" else "Same command failure reappeared without a new recorded hypothesis. "
                                   "Inspect the cause or changed inputs before retrying; this is only a hint."}
