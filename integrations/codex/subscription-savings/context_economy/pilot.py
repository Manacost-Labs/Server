"""Explicit final task outcomes and matched pilot comparisons, never quota guesses."""

import json
import math
import sqlite3

from . import advisor
from .common import encode

METRICS = ("elapsed_seconds", "input_tokens", "output_tokens", "cached_input_tokens",
           "reasoning_tokens", "api_cost_usd", "codex_credits")


def table(store):
    store.db.execute("""CREATE TABLE IF NOT EXISTS pilot_outcomes (
        dataset TEXT, case_id TEXT, variant TEXT, payload TEXT NOT NULL,
        PRIMARY KEY(dataset,case_id,variant))""")
    store.db.commit()


def record(store, value):
    required = {"advice_id", "case_id", "variant", "dataset", "model", "effort", "speed", "accepted", "checks_passed",
                "regressions", "attempts", "rework_cycles", "evidence"}
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - set(METRICS):
        raise ValueError("Outcome has missing or unexpected fields")
    for field in ("advice_id", "case_id", "evidence"):
        if not isinstance(value[field], str) or not value[field].strip() or len(value[field]) > 2000:
            raise ValueError(f"Outcome needs a short nonempty {field}")
    if value["dataset"] not in ("real", "synthetic") or value["variant"] not in ("baseline", "advised"):
        raise ValueError("Choose dataset real/synthetic and variant baseline/advised")
    if value["model"] not in advisor.MODELS:
        raise ValueError("Record the actual executing model tier")
    if value["effort"] not in ("low", "medium", "high", "xhigh", "max", "ultra", "unknown"):
        raise ValueError("Record actual effort or unknown")
    if value["speed"] not in ("standard", "fast", "unknown"):
        raise ValueError("Record actual speed or unknown")
    for field in ("accepted", "checks_passed", "regressions"):
        if type(value[field]) is not bool:
            raise ValueError(f"{field} must be boolean")
    for field in ("attempts", "rework_cycles"):
        if type(value[field]) is not int or value[field] < (1 if field == "attempts" else 0):
            raise ValueError(f"Invalid {field}")
    for field in METRICS:
        number = value.get(field)
        if number is not None and (type(number) not in (int, float) or not math.isfinite(number) or number < 0):
            raise ValueError(f"{field} must be finite, nonnegative or null")
        if number is not None and field.endswith("tokens") and int(number) != number:
            raise ValueError("Token counts must be integers")
    for subset, total in (("cached_input_tokens", "input_tokens"), ("reasoning_tokens", "output_tokens")):
        if value.get(subset) is not None and value.get(total) is not None and value[subset] > value[total]:
            raise ValueError(f"{subset} is part of {total}, not additive")
    try:
        row = store.db.execute("SELECT payload FROM advice WHERE id=?", (value["advice_id"],)).fetchone()
    except sqlite3.OperationalError:
        row = None
    if row is None:
        raise ValueError("Advice must exist in this project's state")
    advice = json.loads(row[0])
    result = dict(value, category=advice["category"], task_hash=advice["task_hash"],
                  advice_status=advice["status"], suggested_model=advice["suggested_model"],
                  advice_request_cost_usd=advice["request_cost_usd"])
    table(store)
    try:
        with store.db:
            store.db.execute("INSERT INTO pilot_outcomes VALUES (?,?,?,?)",
                             (value["dataset"], value["case_id"], value["variant"], encode(result)))
    except sqlite3.IntegrityError as exc:
        raise ValueError("This case/variant is already recorded; do not double-count outcomes") from exc
    return {"recorded": True, "case_id": value["case_id"], "variant": value["variant"]}


def success(row):
    return row["accepted"] and row["checks_passed"] and not row["regressions"]


def summary(store, dataset="real"):
    table(store)
    groups = {}
    for row in store.db.execute("SELECT payload FROM pilot_outcomes WHERE dataset=? ORDER BY case_id,variant",
                                (dataset,)):
        outcome = json.loads(row[0])
        groups.setdefault(outcome["category"], []).append(outcome)
    result = []
    for category, rows in sorted(groups.items()):
        cases = {}
        for row in rows:
            cases.setdefault(row["case_id"], {})[row["variant"]] = row
        paired = [pair for pair in cases.values() if set(pair) == {"baseline", "advised"}
                  and pair["baseline"]["task_hash"] == pair["advised"]["task_hash"]]
        metrics = {}
        for metric in METRICS:
            measured = [p for p in paired if all(p[v].get(metric) is not None for v in p)]
            metrics[metric] = {"measured_pairs": len(measured),
                               "baseline_total": sum(p["baseline"][metric] for p in measured) if measured else None,
                               "advised_total": sum(p["advised"][metric] for p in measured) if measured else None}
        result.append({"category": category, "unique_cases": len(cases), "matched_pairs": len(paired),
                       "pilot_target": "10–20 real tasks; matched cases needed to compare costs",
                       "outcomes": {v: {"count": sum(r["variant"] == v for r in rows),
                                         "successful": sum(r["variant"] == v and success(r) for r in rows),
                                         "attempts": sum(r["attempts"] for r in rows if r["variant"] == v),
                                         "rework_cycles": sum(r["rework_cycles"] for r in rows if r["variant"] == v)}
                                    for v in ("baseline", "advised")},
                       "matched_quality_regressions": sum(success(p["baseline"]) and not success(p["advised"])
                                                          for p in paired),
                       "model_pairs": sorted({(p["baseline"]["model"], p["advised"]["model"]) for p in paired}),
                       "settings": sorted({(r["variant"], r["model"], r["effort"], r["speed"]) for r in rows}),
                       "metrics": metrics})
    return {"dataset": dataset, "groups": result, "automatic_routing": False,
            "notice": "Self-reported final outcomes, not independent verification. Include preparation, "
                      "reviews and failed attempts in totals. Missing costs stay unknown. Codex credits "
                      "must be measured, never inferred from API prices. No automatic graduation. "
                      "Matched task hashes do not establish a controlled experiment or equal difficulty."}
