"""Local task intervals: counters only, never store session messages or credentials."""

import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import time
from pathlib import Path

from .common import encode

WINDOW = 8 * 1024 * 1024
TOKENS = {"input_tokens": "input_tokens", "output_tokens": "output_tokens",
          "cached_input_tokens": "cached_input_tokens", "reasoning_tokens": "reasoning_output_tokens"}


def _session_uuid(identifier, variable):
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", identifier):
        raise ValueError(f"{variable} must contain the current session UUID")


def current_session_with_format():
    """Resolve one exact host-provided Codex or Claude Code session."""
    if os.environ.get("CLAUDECODE") == "1":
        identifier = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
        _session_uuid(identifier, "CLAUDE_CODE_SESSION_ID")
        root = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))) / "projects"
        matches = list(root.glob(f"*/{identifier}.jsonl"))
        session_format = "claude"
    else:
        identifier = os.environ.get("CODEX_SESSION_ID", "")
        _session_uuid(identifier, "CODEX_SESSION_ID")
        root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "sessions"
        matches = list(root.glob(f"*/*/*/*-{identifier}.jsonl"))
        session_format = "codex"
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one local session for {session_format}; found {len(matches)}")
    return matches[0], session_format


def current_session():
    """Return the exact local session path for the active supported client."""
    return current_session_with_format()[0]


def schema(store):
    store.db.executescript("""
        CREATE TABLE IF NOT EXISTS meter_runs (id TEXT PRIMARY KEY, active INTEGER, body TEXT);
        CREATE TABLE IF NOT EXISTS meter_events (
            id INTEGER PRIMARY KEY, run_id TEXT, kind TEXT, created REAL, body TEXT);
        CREATE TABLE IF NOT EXISTS meter_bindings (session_key TEXT PRIMARY KEY, run_id TEXT, role TEXT);
        CREATE INDEX IF NOT EXISTS meter_event_run ON meter_events(run_id,created);
    """)
    # Migrate active legacy intervals without changing their snapshots or history.
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        for row in store.db.execute("SELECT id,body FROM meter_runs WHERE active=1").fetchall():
            body = json.loads(row["body"])
            for part in [dict(body, role="primary"), *body.get("auxiliary", [])]:
                key = encode(part["baseline"]["identity"])
                store.db.execute("INSERT OR IGNORE INTO meter_bindings VALUES(?,?,?)", (key, row["id"], part["role"]))
                owner = store.db.execute("SELECT run_id FROM meter_bindings WHERE session_key=?", (key,)).fetchone()[0]
                if owner != row["id"]:
                    raise ValueError("An active session is already assigned to another task")
        store.db.execute("DROP INDEX IF EXISTS one_active_meter")


def bind(store, identifier):
    """Bind helper events explicitly; never guess their task from project activity."""
    schema(store)
    if identifier and not store.db.execute("SELECT 1 FROM meter_runs WHERE id=? AND active=1", (identifier,)).fetchone():
        raise ValueError("Helper measurement requires an existing active --meter-task-id")
    store.meter_task_id = identifier or None


def active_id(store):
    schema(store)
    row = store.db.execute("SELECT id FROM meter_runs WHERE active=1 AND id=?",
                           (getattr(store, "meter_task_id", None),)).fetchone()
    return row[0] if row else None


def event(store, kind, body):
    schema(store)
    identifier = getattr(store, "meter_task_id", None)
    with store.db:
        store.db.execute("INSERT INTO meter_events VALUES(NULL,?,?,?,?)",
                         (identifier, kind, time.time(), encode(body)))


def remote_event(store, status, usage=None):
    cost = usage.get("cost") if isinstance(usage, dict) else None
    if type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0:
        cost = None
    usage = usage if isinstance(usage, dict) else {}
    tokens = {}
    for target, source in (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens")):
        value = usage.get(source)
        tokens[target] = 0 if status == "cache" else value if type(value) is int and value >= 0 else None
    for target, details, key in (("cached_input_tokens", "prompt_tokens_details", "cached_tokens"),
                                 ("reasoning_tokens", "completion_tokens_details", "reasoning_tokens")):
        values = usage.get(details)
        value = values.get(key) if isinstance(values, dict) else None
        tokens[target] = 0 if status == "cache" else value if type(value) is int and value >= 0 else None
    for subset, total in (("cached_input_tokens", "input_tokens"), ("reasoning_tokens", "output_tokens")):
        if tokens[subset] is not None and tokens[total] is not None and tokens[subset] > tokens[total]:
            tokens[subset] = None
    event(store, "remote", {"status": status, "cost_usd": 0 if status == "cache" else cost, **tokens})


def session_read(path, previous=None, session_format="codex"):
    if session_format == "claude":
        return claude_session_read(path, previous)
    if session_format != "codex":
        raise ValueError("Session format must be codex or claude")
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
        if not previous and info.st_size == 0:
            data["total"] = dict.fromkeys(TOKENS, 0)
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


def _claude_usage(usage):
    if not isinstance(usage, dict):
        return None
    fields = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
    if any(type(usage.get(name)) is not int or not 0 <= usage[name] <= 10**12 for name in fields):
        return None
    details = usage.get("output_tokens_details")
    thinking = details.get("thinking_tokens") if isinstance(details, dict) else None
    if type(thinking) is not int or not 0 <= thinking <= usage["output_tokens"]:
        thinking = None
    return {"input_tokens": sum(usage[name] for name in fields[:3]),
            "cached_input_tokens": usage["cache_read_input_tokens"],
            "output_tokens": usage["output_tokens"], "reasoning_tokens": thinking}


def claude_session_read(path, previous=None):
    """Aggregate each Claude API request once without retaining message content."""
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
        offset = previous["offset"] if previous else 0
        if info.st_size - offset > WINDOW:
            raise ValueError("Claude session exceeds 8 MiB since baseline; start a new Claude session or snapshot sooner")
        stream.seek(offset)
        chunk = stream.read(info.st_size - offset)
    data = dict(previous) if previous else {"total": dict.fromkeys(TOKENS, 0), "settings": [],
                                        "tool_calls": 0, "counter_reset": False,
                                        "usage_events": 0, "seen_requests": {}, "seen_tools": [],
                                        "usage_incomplete": False}
    data["total"] = dict(data["total"])
    data["settings"] = list(data["settings"])
    data["seen_requests"] = dict(data["seen_requests"])
    seen_tools = set(data["seen_tools"])
    data["identity"] = identity
    data["offset"] = offset
    for raw in chunk.splitlines(keepends=True):
        if not raw.endswith(b"\n"):
            break
        data["offset"] += len(raw)
        try:
            item = json.loads(raw)
        except (ValueError, UnicodeError):
            data["usage_incomplete"] = True
            continue
        if not isinstance(item, dict) or item.get("type") != "assistant":
            continue
        message = item.get("message")
        if not isinstance(message, dict):
            data["usage_incomplete"] = True
            continue
        identifier = item.get("requestId") or message.get("id")
        usage = _claude_usage(message.get("usage"))
        if not isinstance(identifier, str) or not 1 <= len(identifier) <= 200 or usage is None:
            data["usage_incomplete"] = True
            continue
        key = hashlib.sha256(identifier.encode()).hexdigest()
        old = data["seen_requests"].get(key)
        if old is None:
            if len(data["seen_requests"]) >= 10000:
                raise ValueError("Claude session has too many requests for a bounded meter")
            data["seen_requests"][key] = usage
            data["usage_events"] += 1
            old = {name: 0 for name in TOKENS}
        elif any(usage[name] is not None and old[name] is not None and usage[name] < old[name]
                 for name in TOKENS):
            data["counter_reset"] = True
        for name in TOKENS:
            if usage[name] is None or old[name] is None:
                data["total"].pop(name, None)
            elif name in data["total"] and usage[name] >= old[name]:
                data["total"][name] += usage[name] - old[name]
        data["seen_requests"][key] = usage
        setting = {"model": message["model"]} if isinstance(message.get("model"), str) and len(message["model"]) <= 100 else {}
        if isinstance(item.get("effort"), str) and len(item["effort"]) <= 100:
            setting["effort"] = item["effort"]
        if setting:
            data["current_setting"] = setting
        if setting and setting not in data["settings"]:
            data["settings"] = [*data["settings"], setting][-20:]
        for block in message.get("content") if isinstance(message.get("content"), list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and isinstance(block.get("id"), str):
                tool = hashlib.sha256(block["id"].encode()).hexdigest()
                if tool not in seen_tools:
                    seen_tools.add(tool)
                    data["tool_calls"] += 1
    data["seen_tools"] = sorted(seen_tools)
    return data


def component(session, role, session_format="codex"):
    snapshot = session_read(session, session_format=session_format)
    if snapshot.get("usage_incomplete"):
        raise ValueError("Claude session history is incomplete; start a new Claude session")
    snapshot["counter_reset"] = False
    snapshot["settings"] = [snapshot["current_setting"]] if snapshot.get("current_setting") else []
    return {"session": str(Path(session).absolute()), "role": role, "baseline": snapshot,
            "latest": snapshot, "baseline_events": snapshot["usage_events"], "session_format": session_format}


def start(store, identifier, session, from_task_start=False, session_format="codex"):
    if not identifier.strip() or len(identifier) > 200:
        raise ValueError("Provide a short task id")
    schema(store)
    body = dict(component(session, "primary", session_format), started=time.time(), auxiliary=[],
                from_task_start=bool(from_task_start))
    try:
        with store.db:
            store.db.execute("BEGIN IMMEDIATE")
            store.db.execute("INSERT INTO meter_bindings VALUES(?,?,?)",
                             (encode(body["baseline"]["identity"]), identifier, "primary"))
            store.db.execute("INSERT INTO meter_runs VALUES (?,1,?)", (identifier, encode(body)))
    except sqlite3.IntegrityError as exc:
        raise ValueError("Session already measured or task id previously used; select a distinct session/id") from exc
    return {"task_id": identifier, "active": True, "helper_environment": {"CODEX_ECONOMY_TASK_ID": identifier},
            "notice": "Only this session interval is measured. Bind helpers explicitly; attach auxiliary sessions before work."}


def attach(store, identifier, session, role, session_format="codex"):
    if role not in ("helper", "compaction"):
        raise ValueError("Auxiliary role must be helper or compaction")
    schema(store)
    extra = component(session, role, session_format)
    try:
        with store.db:
            store.db.execute("BEGIN IMMEDIATE")
            row = store.db.execute("SELECT body FROM meter_runs WHERE id=? AND active=1", (identifier,)).fetchone()
            if row is None:
                raise ValueError("Unknown active measurement")
            body = json.loads(row[0])
            store.db.execute("INSERT INTO meter_bindings VALUES(?,?,?)",
                             (encode(extra["baseline"]["identity"]), identifier, role))
            body.setdefault("auxiliary", []).append(extra)
            store.db.execute("UPDATE meter_runs SET body=? WHERE id=?", (encode(body), identifier))
    except sqlite3.IntegrityError as exc:
        raise ValueError("Session already assigned; never count a session twice") from exc
    return {"task_id": identifier, "attached": str(Path(session).absolute()), "role": role,
            "notice": "Only subsequent usage is measured; earlier preparation remains outside this interval."}


def counters(part, cancelled=False):
    base, last = part["baseline"], part["latest"]
    fresh = (last["usage_events"] > part["baseline_events"] and not last["counter_reset"]
             and not last.get("usage_incomplete") and not cancelled)
    result = {k: last["total"][k] - base["total"][k]
              if fresh and k in last["total"] and k in base["total"] else None for k in TOKENS}
    for subset, total in (("cached_input_tokens", "input_tokens"), ("reasoning_tokens", "output_tokens")):
        if result[subset] is not None and result[total] is not None and result[subset] > result[total]:
            result[subset] = None
    return result


def known_sum(values):
    values = list(values)
    return sum(values) if all(v is not None for v in values) else None


def report(store, identifier, finish=False, coverage_evidence=""):
    if coverage_evidence and (not finish or not 12 <= len(coverage_evidence.strip()) <= 2000):
        raise ValueError("Coverage evidence requires finish and 12–2000 characters")
    schema(store)
    # Serialize snapshot/finish operations so a stale snapshot cannot reactivate a finished task.
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        row = store.db.execute("SELECT active,body FROM meter_runs WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("Unknown measured task")
        body = json.loads(row["body"])
        if row["active"]:
            for part in [body, *body.get("auxiliary", [])]:
                part["latest"] = session_read(part["session"], part["latest"], part.get("session_format", "codex"))
            body["observed"] = time.time()
            if finish:
                body["finished"] = body["observed"]
                body["coverage_evidence"] = coverage_evidence
                store.db.execute("DELETE FROM meter_bindings WHERE run_id=?", (identifier,))
            store.db.execute("UPDATE meter_runs SET active=?,body=? WHERE id=?",
                             (0 if finish else 1, encode(body), identifier))
    components = [{"role": part.get("role", "primary"), "session": part["session"],
                   "session_format": part.get("session_format", "codex"),
                   "model_settings": part["latest"]["settings"], **counters(part, body.get("cancelled"))}
                  for part in [body, *body.get("auxiliary", [])]]
    tokens = {k: known_sum(c[k] for c in components) for k in TOKENS}
    rows = [(r["kind"], r["created"], json.loads(r["body"])) for r in store.db.execute(
        "SELECT kind,created,body FROM meter_events WHERE run_id=? ORDER BY id", (identifier,))]
    end = body.get("finished") or body.get("observed") or body["started"]
    unattributed = store.db.execute("SELECT count(*) FROM meter_events WHERE run_id IS NULL AND created>=? AND created<=?",
                                    (body["started"], end)).fetchone()[0]
    late = sum(created > end for _, created, _ in rows) if body.get("finished") else 0
    remote = [r for kind, _, r in rows if kind == "remote"]
    helper_tokens = {k: known_sum(r.get(k) for r in remote) if not unattributed else None for k in TOKENS}
    complete = bool(body.get("finished") and body.get("from_task_start") and body.get("coverage_evidence")
                    and not body.get("cancelled") and not unattributed and not late
                    and all(v is not None for v in tokens.values())
                    and all(v is not None for v in helper_tokens.values())
                    and all(r["cost_usd"] is not None for r in remote))
    return {"task_id": identifier, "active": bool(row["active"] and not finish), "cancelled": bool(body.get("cancelled")), **tokens,
            "elapsed_seconds": end - body["started"], "model_settings": body["latest"]["settings"],
            "codex_components": components, "session_components": components,
            "tool_calls": sum(p["latest"]["tool_calls"] - p["baseline"]["tool_calls"] for p in [body, *body.get("auxiliary", [])]),
            "helper_api_cost_usd": known_sum(r["cost_usd"] for r in remote) if not unattributed else None,
            "helper_input_tokens": helper_tokens["input_tokens"], "helper_output_tokens": helper_tokens["output_tokens"],
            "all_model_input_tokens": known_sum([tokens["input_tokens"], helper_tokens["input_tokens"]]),
            "all_model_output_tokens": known_sum([tokens["output_tokens"], helper_tokens["output_tokens"]]),
            "all_model_cached_input_tokens": known_sum([tokens["cached_input_tokens"], helper_tokens["cached_input_tokens"]]),
            "all_model_reasoning_tokens": known_sum([tokens["reasoning_tokens"], helper_tokens["reasoning_tokens"]]),
            "remote_calls": sum(r["status"] != "cache" for r in remote),
            "cache_hits": sum(r["status"] == "cache" for r in remote),
            "commands": sum(kind == "command" for kind, _, _ in rows),
            "command_failures": sum(kind == "command" and r["exit_code"] != 0 for kind, _, r in rows),
            "unattributed_events": unattributed, "late_events": late,
            "coverage": {"status": "declared-complete" if complete else "partial-or-unknown",
                         "from_task_start": bool(body.get("from_task_start")), "evidence": body.get("coverage_evidence", "")},
            "codex_credits": None, "api_cost_usd": None,
            "notice": "Client counters may lag or omit usage. Session counters include attached sessions; all_model counters "
                      "also include instrumented remote helpers. Cached/reasoning tokens are subsets. Completeness is "
                      "an explicit operator attestation, not proof of coverage. Unbound events may belong to this task; "
                      "unknown costs/counters remain null. Quality requires separate acceptance evidence."}


def cancel(store, identifier):
    schema(store)
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        row = store.db.execute("SELECT body FROM meter_runs WHERE id=? AND active=1", (identifier,)).fetchone()
        if row is None:
            raise ValueError("Unknown active measurement")
        body = dict(json.loads(row[0]), cancelled=True, finished=time.time())
        store.db.execute("UPDATE meter_runs SET active=0,body=? WHERE id=?", (encode(body), identifier))
        store.db.execute("DELETE FROM meter_bindings WHERE run_id=?", (identifier,))
    return {"task_id": identifier, "cancelled": True, "notice": "Incomplete interval retained for diagnosis, not a pilot outcome."}
