"""Validate paired task records. No invented results or quota conversion."""
import argparse
import json
import math
import re
import statistics
from fractions import Fraction
from pathlib import Path

COUNTERS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "model_launches",
            "retries", "rework_count")
METRICS = (*COUNTERS, "auxiliary_api_cost_usd", "elapsed_seconds")
IDENTITY = ("case_id", "task", "source_repository", "source_commit", "model", "reasoning_effort", "speed")


def validate(row):
    required = {"schema", "variant", "dataset", "measurement", "tests", "quality", "evidence", *IDENTITY, *METRICS}
    if isinstance(row, dict) and row.get("schema") == 2:
        required.add("coverage")
    if not isinstance(row, dict) or set(row) != required or type(row["schema"]) is not int or row["schema"] not in (1, 2):
        raise ValueError("Record must use the complete benchmark v1/v2 schema, without extra fields")
    if row["schema"] == 2:
        coverage = row["coverage"]
        fields = {"from_task_start", "helpers_included", "compaction_included", "finished", "evidence"}
        if (not isinstance(coverage, dict) or set(coverage) != fields or
                not isinstance(coverage["evidence"], str) or
                any(type(coverage[k]) is not bool for k in fields - {"evidence"})):
            raise ValueError("Coverage must explicitly declare all phases and provide evidence")
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
    mismatch = [k for k in (*IDENTITY, "dataset", "schema") if baseline[k] != economy[k]]
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
    if baseline["schema"] == 2:
        complete = complete and all(covered(row) for row in (baseline, economy))
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


def covered(row):
    value = row.get("coverage", {})
    return (row["schema"] == 2 and bool(value.get("evidence", "").strip()) and
            all(value.get(k) is True for k in ("from_task_start", "helpers_included", "compaction_included", "finished")))


def assess(pairs):
    """Conservative pilot gate; source evidence remains operator-provided, never invented."""
    if not isinstance(pairs, list) or len(pairs) > 100:
        raise ValueError("Assess at most 100 explicit matched pairs")
    seen, eligible, excluded = set(), [], []
    incomplete_real = False
    for baseline, economy in pairs:
        result = compare(baseline, economy)
        key = (baseline["source_repository"], baseline["case_id"])
        if key in seen:
            raise ValueError("Duplicate task pair; repetitions are not independent cases")
        seen.add(key)
        reason = None
        if result["dataset"] != "real":
            reason = "synthetic"
        elif (result["status"] != "matched-observations" or not all(covered(r) for r in (baseline, economy)) or
              baseline["input_tokens"] + baseline["output_tokens"] <= 0 or baseline["elapsed_seconds"] <= 0):
            reason = "incomplete-coverage-or-counters"
            incomplete_real = True
        if reason:
            excluded.append({"case_id": baseline["case_id"], "reason": reason})
        else:
            eligible.append((baseline, economy))
    reductions = [Fraction(b["input_tokens"] + b["output_tokens"] - e["input_tokens"] - e["output_tokens"],
                           b["input_tokens"] + b["output_tokens"])
                  for b, e in eligible]
    times = [e["elapsed_seconds"] / b["elapsed_seconds"] for b, e in eligible]
    median_reduction = statistics.median(reductions) if reductions else None
    median_time = statistics.median(times) if times else None
    quality = all(r["tests"]["passed"] and r["quality"]["accepted"] for pair in eligible for r in pair) if eligible else None
    no_rework_increase = all(e["rework_count"] <= b["rework_count"] and e["retries"] <= b["retries"]
                            for b, e in eligible) if eligible else None
    enough = len(eligible) >= 10 and not incomplete_real
    passed = enough and quality and no_rework_increase and median_reduction >= Fraction(1, 5) and median_time <= 1
    return {"status": ("pilot-target-met" if passed else "pilot-target-not-met") if enough else "insufficient-evidence",
            "eligible_pairs": len(eligible), "excluded": excluded, "minimum_real_pairs": 10,
            "quality_preserved": quality, "no_rework_increase": no_rework_increase,
            "median_token_reduction": float(median_reduction) if median_reduction is not None else None,
            "target_token_reduction": .2,
            "median_elapsed_ratio": median_time, "maximum_median_elapsed_ratio": 1,
            "auxiliary_api_cost_usd": {"baseline": sum(b["auxiliary_api_cost_usd"] for b, _ in eligible),
                                       "economy": sum(e["auxiliary_api_cost_usd"] for _, e in eligible)} if eligible else None,
            "subscription_savings_percent": None,
            "notice": "Token metric is input+output across main and helper models; cached/reasoning subsets are not added twice. "
                      "Operator-provided coverage/quality evidence is not independently verified. This small pilot gate "
                      "does not prove general quality, monetary savings or subscription quota savings."}


def read_record(path):
    with Path(path).open("rb") as stream:
        data = stream.read(65537)
    if len(data) > 65536:
        raise ValueError("Benchmark file exceeds 64 KiB")
    return json.loads(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--economy", type=Path)
    parser.add_argument("--manifest", type=Path, help="JSON array of {baseline,economy} file paths relative to manifest")
    args = parser.parse_args()
    try:
        if args.manifest:
            if args.baseline or args.economy:
                raise ValueError("Use either a manifest or one baseline/economy pair")
            entries = read_record(args.manifest)
            if not isinstance(entries, list) or len(entries) > 100:
                raise ValueError("Manifest must contain at most 100 pairs")
            pairs = []
            for entry in entries:
                if (not isinstance(entry, dict) or set(entry) != {"baseline", "economy"} or
                        any(not isinstance(v, str) or not v for v in entry.values())):
                    raise ValueError("Manifest entries must name baseline and economy files")
                pairs.append(tuple(read_record(args.manifest.parent / entry[k]) for k in ("baseline", "economy")))
            result = assess(pairs)
        elif args.baseline and args.economy:
            result = compare(read_record(args.baseline), read_record(args.economy))
        else:
            raise ValueError("Provide --manifest or both --baseline and --economy")
        print(json.dumps(result, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"benchmark: {exc}\n")


if __name__ == "__main__":
    main()
