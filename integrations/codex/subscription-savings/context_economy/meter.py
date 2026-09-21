"""Local task intervals: counters only, never store session messages or credentials."""

import json
import math
import os
import stat
import time
from pathlib import Path

from .common import encode

WINDOW = 8 * 1024 * 1024
TOKENS = {"input_tokens": "input_tokens", "output_tokens": "output_tokens",
          "cached_input_tokens": "cached_input_tokens", "reasoning_tokens": "reasoning_output_tokens"}


def schema(store):
    store.db.executescript("""
        CREATE TABLE IF NOT EXISTS meter_runs (id TEXT PRIMARY KEY, active INTEGER, body TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_meter ON meter_runs(active) WHERE active=1;
        CREATE TABLE IF NOT EXISTS meter_events (
            id INTEGER PRIMARY KEY, run_id TEXT, kind TEXT, created REAL, body TEXT);
    """)


def active_id(store):
    schema(store)
    row = store.db.execute("SELECT id FROM meter_runs WHERE active=1").fetchone()
    return row[0] if row else None


def event(store, kind, body):
    identifier = active_id(store)
    if identifier:
        with store.db:
            store.db.execute("INSERT INTO meter_events VALUES(NULL,?,?,?,?)",
                             (identifier, kind, time.time(), encode(body)))


def remote_event(store, status, usage=None):
    cost = usage.get("cost") if isinstance(usage, dict) else None
    if type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0:
        cost = None
    event(store, "remote", {"status": status, "cost_usd": 0 if status == "cache" else cost})


def session_read(path, previous=None):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("Session path must not contain symlinks")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("Select a regular session file owned by this user")
        identity = [info.st_dev, info.st_ino]
        if previous and (previous["identity"] != identity or info.st_size < previous["offset"]):
            raise ValueError("Session was replaced or truncated; start a new measurement")
        offset = previous["offset"] if previous else max(0, info.st_size - WINDOW)
        if info.st_size - offset > WINDOW:
            raise ValueError("More than 8 MiB since snapshot; snapshot more often or start a new interval")
        stream.seek(offset)
        chunk = stream.read(info.st_size - offset)
        if not previous and offset:
            boundary = chunk.find(b"\n")
            skipped = boundary + 1 if boundary >= 0 else len(chunk)
            chunk = chunk[skipped:]  # Tail may begin in the middle of an event.
            offset += skipped
        data = dict(previous) if previous else {"total": {}, "settings": [], "tool_calls": 0,
                                                "counter_reset": False, "usage_events": 0}
        data["identity"] = identity
        data["offset"] = offset
        for raw in chunk.splitlines(keepends=True):
            if not raw.endswith(b"\n"):
                break  # An event is still being written; do not advance past it.
            data["offset"] += len(raw)
            try:
                item = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(item, dict) or not isinstance(item.get("payload"), dict):
                continue
            payload = item["payload"]
            if item.get("type") == "event_msg" and payload.get("type") == "token_count":
                usage_info = payload.get("info")
                total = usage_info.get("total_token_usage") if isinstance(usage_info, dict) else None
                if not isinstance(total, dict):
                    continue
                clean = {k: total[v] for k, v in TOKENS.items()
                         if type(total.get(v)) is int and total[v] >= 0}
                if any(clean[k] < data["total"][k] for k in clean.keys() & data["total"].keys()):
                    data["counter_reset"] = True
                data["total"] = clean
                data["usage_events"] += 1
            elif item.get("type") == "turn_context":
                setting = {k: payload.get(k) for k in ("model", "effort", "speed")
                           if isinstance(payload.get(k), str) and len(payload[k]) <= 100}
                if setting:
                    data["current_setting"] = setting
                if setting and setting not in data["settings"]:
                    data["settings"] = [*data["settings"], setting][-20:]
            elif item.get("type") == "response_item" and payload.get("type") in ("function_call", "custom_tool_call"):
                data["tool_calls"] += 1
    return data


def start(store, identifier, session):
    if not identifier.strip() or len(identifier) > 200:
        raise ValueError("Provide a short task id")
    schema(store)
    if store.db.execute("SELECT 1 FROM meter_runs WHERE active=1 OR id=?", (identifier,)).fetchone():
        raise ValueError("A task is already active or this id was used; finish it or choose a new id")
    snapshot = session_read(session)
    snapshot["counter_reset"] = False
    snapshot["settings"] = [snapshot["current_setting"]] if snapshot.get("current_setting") else []
    body = {"started": time.time(), "session": str(Path(session).absolute()), "baseline": snapshot,
            "latest": snapshot, "baseline_events": snapshot["usage_events"]}
    with store.db:
        store.db.execute("INSERT INTO meter_runs VALUES (?,1,?)", (identifier, encode(body)))
    return {"task_id": identifier, "active": True, "notice": "Only this session interval is measured; keep it task-specific."}


def report(store, identifier, finish=False):
    schema(store)
    row = store.db.execute("SELECT active,body FROM meter_runs WHERE id=?", (identifier,)).fetchone()
    if row is None:
        raise ValueError("Unknown measured task")
    body = json.loads(row["body"])
    if row["active"]:
        body["latest"] = session_read(body["session"], body["latest"])
        body["observed"] = time.time()
        if finish:
            body["finished"] = body["observed"]
        with store.db:
            store.db.execute("UPDATE meter_runs SET active=?,body=? WHERE id=?",
                             (0 if finish else 1, encode(body), identifier))
    base, last = body["baseline"], body["latest"]
    fresh = last["usage_events"] > body["baseline_events"] and not last["counter_reset"] and not body.get("cancelled")
    tokens = {k: last["total"][k] - base["total"][k]
              if fresh and k in last["total"] and k in base["total"] else None for k in TOKENS}
    for subset, total in (("cached_input_tokens", "input_tokens"), ("reasoning_tokens", "output_tokens")):
        if tokens[subset] is not None and tokens[total] is not None and tokens[subset] > tokens[total]:
            tokens[subset] = None
    rows = [(r["kind"], json.loads(r["body"])) for r in store.db.execute(
        "SELECT kind,body FROM meter_events WHERE run_id=? ORDER BY id", (identifier,))]
    remote = [r for kind, r in rows if kind == "remote"]
    known = all(r["cost_usd"] is not None for r in remote)
    return {"task_id": identifier, "active": bool(row["active"] and not finish), "cancelled": bool(body.get("cancelled")), **tokens,
            "elapsed_seconds": (body.get("finished") or body.get("observed") or body["started"]) - body["started"],
            "model_settings": last["settings"], "tool_calls": last["tool_calls"] - base["tool_calls"],
            "helper_api_cost_usd": sum(r["cost_usd"] for r in remote) if known else None,
            "remote_calls": sum(r["status"] != "cache" for r in remote),
            "cache_hits": sum(r["status"] == "cache" for r in remote),
            "commands": sum(kind == "command" for kind, _ in rows),
            "command_failures": sum(kind == "command" and r["exit_code"] != 0 for kind, r in rows),
            "codex_credits": None, "api_cost_usd": None,
            "notice": "Latest client-reported interval, which can lag the current turn and include other "
                      "work in the same session. Helper cost covers "
                      "this project's instrumented calls only, not all API spend. Cached/reasoning tokens "
                      "are subsets; credits and unreported counters stay unknown. Quality needs explicit confirmation."}


def cancel(store, identifier):
    schema(store)
    row = store.db.execute("SELECT body FROM meter_runs WHERE id=? AND active=1", (identifier,)).fetchone()
    if row is None:
        raise ValueError("Unknown active measurement")
    body = dict(json.loads(row[0]), cancelled=True, finished=time.time())
    with store.db:
        store.db.execute("UPDATE meter_runs SET active=0,body=? WHERE id=?", (encode(body), identifier))
    return {"task_id": identifier, "cancelled": True, "notice": "Incomplete interval retained for diagnosis, not a pilot outcome."}
