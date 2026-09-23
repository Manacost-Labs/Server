"""OpenRouter-only transport, explicit credentials, shared conservative reservations."""

import json
import math
import os
import shlex
import sqlite3
import stat
import time
import urllib.request
from pathlib import Path

from . import meter
from .common import Store, digest, encode
from .typesafe import NoRedirect

MODELS = {"jev": "typesafe/jev-1.13", "gemma": "google/gemma-4-26b-a4b-it"}
ENDPOINTS = {"jev": "https://openrouter.ai/api/alpha/decisions",
             "gemma": "https://openrouter.ai/api/v1/chat/completions"}
# Full advertised context at capped provider prices, including max generated tokens.
# Unknown/failed charges retain this reservation; these are not measured costs.
RESERVATIONS = {"jev": 0.003, "gemma": 0.025}
MAX_RESPONSE = 128000


def api_key():
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    path = Path.home() / ".config/codex-context-economy/remote.env"
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise ValueError("remote.env must be a private regular file owned by this user")
        text = stream.read(16385)
    if len(text) > 16384:
        raise ValueError("Credential file too large")
    for line in text.splitlines():
        if line.strip().startswith("OPENROUTER_API_KEY="):
            parts = shlex.split(line.split("=", 1)[1], comments=True)
            if len(parts) == 1 and parts[0]:
                return parts[0]
    raise ValueError("OPENROUTER_API_KEY is missing")


class Ledger:
    def __init__(self, directory=None):
        # Same ledger for every project; --state-dir does not reset this cap.
        self.store = Store(Path.home(), directory)
        self.db = self.store.db
        self.db.execute("""CREATE TABLE IF NOT EXISTS remote_reservations (
            id INTEGER PRIMARY KEY, created REAL, provider TEXT, request_hash TEXT,
            reserved REAL, charged REAL, status TEXT)""")
        self.db.commit()

    def reserve(self, provider, fingerprint, budget, amount=None, call_limit=None):
        if type(budget) not in (float, int) or not math.isfinite(budget) or not 0 < budget <= 1:
            raise ValueError("Pilot daily budget must be greater than zero and at most $1")
        amount = RESERVATIONS[provider] if amount is None else amount
        if type(amount) not in (float, int) or not math.isfinite(amount) or not 0 < amount <= 1:
            raise ValueError("Reservation must be a finite positive amount up to $1")
        if call_limit is not None and (type(call_limit) is not int or not 1 <= call_limit <= 100):
            raise ValueError("Shared call limit must be 1–100")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if call_limit is not None:
                count = self.db.execute("SELECT COUNT(*) FROM remote_reservations WHERE created>? AND provider LIKE 'quality:%'",
                                        (time.time() - 86400,)).fetchone()[0]
                if count >= call_limit:
                    raise ValueError("Shared 24-hour retrieval call budget exhausted")
            used = self.db.execute("SELECT COALESCE(SUM(COALESCE(charged,reserved)),0) "
                                   "FROM remote_reservations WHERE created > ?",
                                   (time.time() - 86400,)).fetchone()[0]
            if used + amount > budget + 1e-12:
                raise ValueError("Shared 24-hour remote budget exhausted")
            row = self.db.execute("INSERT INTO remote_reservations VALUES(NULL,?,?,?,?,NULL,?)",
                                  (time.time(), provider, fingerprint, amount, "reserved"))
            return row.lastrowid

    def finish(self, identifier, response):
        usage = response.get("usage") if isinstance(response, dict) else None
        cost = usage.get("cost") if isinstance(usage, dict) else None
        if type(cost) not in (float, int) or not math.isfinite(cost) or cost < 0:
            cost = None
        with self.db:
            self.db.execute("UPDATE remote_reservations SET charged=?,status=? WHERE id=?",
                            (cost, "reported" if cost is not None else "unknown", identifier))

    def summary(self):
        row = self.db.execute("SELECT COUNT(*),COALESCE(SUM(charged),0),"
                              "COALESCE(SUM(CASE WHEN charged IS NULL THEN reserved ELSE 0 END),0) "
                              "FROM remote_reservations WHERE created > ?", (time.time() - 86400,)).fetchone()
        return dict(requests=row[0], reported_cost_usd=row[1], unknown_reserved_usd=row[2])

    def close(self):
        self.store.close()


def send(provider, payload, key, timeout):
    request = urllib.request.Request(ENDPOINTS[provider], data=encode(payload).encode(), headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    # Do not inherit proxy settings; neither credential nor request may follow redirects.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("Remote response exceeds 128 KB")
    return json.loads(raw)


def request(store, ledger, provider, payload, budget, validate, timeout=15):
    if not 0 < timeout <= 30:
        raise ValueError("Remote timeout must be in (0,30]")
    store.db.execute("CREATE TABLE IF NOT EXISTS assistant_cache (id TEXT PRIMARY KEY, created REAL, body TEXT)")
    store.db.commit()
    fingerprint = digest(encode(["assist-v1", provider, payload]).encode())
    row = store.db.execute("SELECT body FROM assistant_cache WHERE id=? AND created>?",
                           (fingerprint, time.time() - 3600,)).fetchone()
    if row:
        try:
            response = json.loads(row[0])
            result = validate(response)
            meter.remote_event(store, "cache")
            return result, {"provider": provider, "status": "cache", "usage": response.get("usage"),
                            "request_cost_usd": 0}
        except (ValueError, TypeError, KeyError):
            pass
    key = api_key()  # Missing credentials cannot spend a reservation.
    identifier = ledger.reserve(provider, fingerprint, budget)
    recorded = False
    try:
        response = send(provider, payload, key, timeout)
        ledger.finish(identifier, response)
        meter.remote_event(store, "remote", response.get("usage") if isinstance(response, dict) else None)
        recorded = True
        result = validate(response)
        with store.db:
            store.db.execute("INSERT OR REPLACE INTO assistant_cache VALUES (?,?,?)",
                             (fingerprint, time.time(), encode(response)))
        usage = response.get("usage")
        cost = usage.get("cost") if isinstance(usage, dict) else None
        if type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0:
            cost = None
        return result, {"provider": provider, "status": "remote", "usage": usage, "request_cost_usd": cost}
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        # Failed or unknown requests are not free. Never log keys or provider bodies.
        raise ValueError("Remote request failed; original local context retained") from None
    finally:
        if not recorded:
            meter.remote_event(store, "failed")
