"""Validate paired task records. No invented results or quota conversion."""
import argparse
import json
import math
import re
from pathlib import Path

COUNTERS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "model_launches",
            "retries", "rework_count")
METRICS = (*COUNTERS, "auxiliary_api_cost_usd", "elapsed_seconds")
IDENTITY = ("case_id", "task", "source_repository", "source_commit", "model", "reasoning_effort", "speed")


def validate(row):
    required = {"schema", "variant", "dataset", "measurement", "tests", "quality", "evidence", *IDENTITY, *METRICS}
    if not isinstance(row, dict) or set(row) != required or row["schema"] != 1:
        raise ValueError("Record must use the complete benchmark v1 schema, without extra fields")
    if row["variant"] not in ("baseline", "economy") or row["dataset"] not in ("real", "synthetic"):
        raise ValueError("Invalid benchmark variant/dataset")
    if row["measurement"] not in ("observed", "unknown"):
        raise ValueError("Estimates cannot be entered as observed benchmark counters")
    for field in IDENTITY:
        if not isinstance(row[field], str) or not row[field].strip():
            raise ValueError("Missing identity: " + field)
    if not re.fullmatch(r"[0-9a-f]{40}", row["source_commit"]):
        raise ValueError("source_commit must be the full starting Git commit")
    for field in METRICS:
        value = row[field]
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError("Invalid metric: " + field)
        if field in COUNTERS and value is not None and type(value) is not int:
            raise ValueError("Counters must be integers: " + field)
    for subset, total in (("cached_input_tokens", "input_tokens"), ("reasoning_tokens", "output_tokens")):
        if row[subset] is not None and row[total] is not None and row[subset] > row[total]:
            raise ValueError(f"{subset} is included in {total}")
    for name, fields in (("tests", {"passed", "command", "evidence"}),
                         ("quality", {"accepted", "criteria", "rework_notes"})):
        value = row[name]
        if not isinstance(value, dict) or set(value) != fields:
            raise ValueError("Incomplete " + name)
        boolean = "passed" if name == "tests" else "accepted"
        if value[boolean] is not None and type(value[boolean]) is not bool:
            raise ValueError("Invalid outcome boolean")
        if any(not isinstance(value[k], str) for k in fields - {boolean}):
            raise ValueError("Outcome evidence must be text")
    if not isinstance(row["evidence"], str):
        raise ValueError("Evidence must be text")
    return row


def compare(baseline, economy):
    for row in (baseline, economy):
        validate(row)
    if (baseline["variant"], economy["variant"]) != ("baseline", "economy"):
        raise ValueError("Supply baseline then economy")
    mismatch = [k for k in (*IDENTITY, "dataset") if baseline[k] != economy[k]]
    if baseline["quality"]["criteria"] != economy["quality"]["criteria"]:
        mismatch.append("acceptance criteria")
    if baseline["tests"]["command"] != economy["tests"]["command"]:
        mismatch.append("verification command")
    if mismatch:
        raise ValueError("Unmatched pair: " + ", ".join(mismatch))
    complete = all(row["measurement"] == "observed" and row["evidence"].strip() and
                   all(row[k] is not None for k in METRICS) and
                   all(row[k] != "unknown" for k in ("model", "reasoning_effort", "speed")) and
                   row["tests"]["passed"] is not None and row["quality"]["accepted"] is not None and
                   row["tests"]["command"].strip() and row["tests"]["evidence"].strip() and
                   row["quality"]["criteria"].strip() for row in (baseline, economy))
    return {"status": "matched-observations" if complete else "incomplete",
            "dataset": baseline["dataset"], "case_id": baseline["case_id"],
            "quality_preserved": (all(row["tests"]["passed"] and row["quality"]["accepted"]
                                      for row in (baseline, economy)) if complete else None),
            "economy_minus_baseline": {k: economy[k] - baseline[k]
                                       if economy[k] is not None and baseline[k] is not None else None for k in METRICS},
            "subscription_savings_percent": None,
            "notice": "Cached input is included in input; reasoning is included in output. "
                      "Include preparation, compaction, failed attempts and rework. "
                      "One pair is not a general quality or quota guarantee."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--economy", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(compare(json.loads(args.baseline.read_text()), json.loads(args.economy.read_text())), indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"benchmark: {exc}\n")


if __name__ == "__main__":
    main()
