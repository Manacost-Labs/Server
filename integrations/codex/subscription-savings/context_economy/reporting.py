"""Explicit per-attempt measurements; unknown cost is never treated as zero."""

import json
import math
import sqlite3

from .common import encode

GROUP_FIELDS = ("dataset", "variant", "model", "effort", "speed")
NUMBERS = ("elapsed_seconds", "input_tokens", "output_tokens", "cached_input_tokens",
           "reasoning_tokens", "api_cost_usd", "typesafe_cost_usd", "tool_calls")


def record(store, value):
    if not isinstance(value, dict):
        raise ValueError("Attempt must be a JSON object")
    for field in (*GROUP_FIELDS, "attempt_id", "task_id"):
        if not isinstance(value.get(field), str) or not value[field].strip() or len(value[field]) > 200:
            raise ValueError(f"Attempt requires a short nonempty {field}")
    if type(value.get("success")) is not bool:
        raise ValueError("Attempt success must be true or false")
    if value["variant"] not in {"baseline", "local", "typesafe"}:
        raise ValueError("Variant must be baseline, local or typesafe")
    allowed = set(GROUP_FIELDS) | set(NUMBERS) | {"attempt_id", "task_id", "success", "notes"}
    if value.keys() - allowed:
        raise ValueError("Unknown attempt fields; do not mix quota estimates into token measurements")
    for field in NUMBERS:
        number = value.get(field)
        if number is not None and (type(number) not in (int, float) or not math.isfinite(number) or number < 0):
            raise ValueError(f"{field} must be a finite nonnegative number or null")
        if number is not None and (field.endswith("tokens") or field == "tool_calls") and int(number) != number:
            raise ValueError(f"{field} must be an integer")
    for subset, total in (("cached_input_tokens", "input_tokens"), ("reasoning_tokens", "output_tokens")):
        if value.get(subset) is not None and value.get(total) is not None and value[subset] > value[total]:
            raise ValueError(f"{subset} is included in {total}, not additive")
    if len(encode(value)) > 16000:
        raise ValueError("Attempt record too large")
    try:
        with store.db:
            store.db.execute("INSERT INTO attempts VALUES (?, ?)", (value["attempt_id"], encode(value)))
    except sqlite3.IntegrityError as exc:
        raise ValueError("Attempt id already exists; no duplicate measurements") from exc


def summary(store, end_to_end=False):
    fields = ("dataset", "variant") if end_to_end else GROUP_FIELDS
    groups = {}
    for row in store.db.execute("SELECT payload FROM attempts ORDER BY id"):
        value = json.loads(row[0])
        groups.setdefault(tuple(value[field] for field in fields), []).append(value)
    result = []
    for key, attempts in sorted(groups.items()):
        row = dict(zip(fields, key))
        row["model_settings"] = sorted({(a["model"], a["effort"], a["speed"]) for a in attempts})
        completed = {a["task_id"] for a in attempts if a["success"]}
        row.update(attempts=len(attempts), task_ids=sorted({a["task_id"] for a in attempts}),
                   completed_task_ids=sorted(completed), completed_tasks=len(completed))
        for field in NUMBERS:
            values = [a.get(field) for a in attempts]
            row["total_" + field] = sum(values) if all(v is not None for v in values) else None
        known = row["total_input_tokens"] is not None and row["total_output_tokens"] is not None
        row["tokens_per_completed_task"] = ((row["total_input_tokens"] + row["total_output_tokens"])
                                             / len(completed) if completed and known else None)
        # All attempts count, including failed work; no summation of cached/reasoning subsets.
        result.append(row)
    return result
