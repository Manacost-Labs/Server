"""Executable, risk-selected engineering/design gates with honest bounded diagnostics."""

import contextlib
import math
import shutil
import sys
import time
import uuid
from pathlib import Path

from . import output, packing
from .common import digest, encode, read_source
from .quality_common import cache_get, cache_put, resource_lock
from .quality_policy import TIERS, matches, route


def plan(config, paths, risk="low", task_type="implementation", family=None):
    selected = route(paths, task_type, risk, config.get("stack"))
    checks = config.get("checks")
    if not isinstance(checks, list) or not 1 <= len(checks) <= 60:
        raise ValueError("Configure 1–60 checks")
    ids = set()
    result = []
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("id"), str) or check["id"] in ids:
            raise ValueError("Checks require unique string identifiers")
        ids.add(check["id"])
        if check.get("tier", "fast") not in TIERS:
            raise ValueError("Unknown check tier")
        argv = check.get("argv")
        if not isinstance(argv, list) or not argv or len(argv) > 100 or any(
                not isinstance(a, str) or not a or len(a) > 2000 for a in argv):
            raise ValueError("Check argv must be a bounded nonempty string array (no shell expansion)")
        patterns = check.get("paths", [])
        if not isinstance(patterns, list) or any(not isinstance(p, str) for p in patterns):
            raise ValueError("Check path triggers must be a string array")
        reason = None
        if family and check.get("family", "engineering") != family:
            reason = "different family"
        elif not matches(paths, patterns):
            reason = "outside changed paths"
        elif TIERS[check.get("tier", "fast")] > TIERS[selected["tier"]]:
            reason = "higher verification tier"
        expanded = []
        for argument in argv:
            if argument in {"{changed}", "{changed_php}", "{changed_go}", "{changed_js}"}:
                suffixes = {"{changed_php}": {".php"}, "{changed_go}": {".go"},
                            "{changed_js}": {".js", ".jsx", ".ts", ".tsx"}}
                chosen = [p for p in paths if argument == "{changed}" or Path(p).suffix in suffixes[argument]]
                if not chosen and reason is None:
                    raise ValueError("Selected check needs matching changed source files")
                expanded.extend("./" + p if p.startswith("-") else p for p in chosen)
            elif argument == "{go_packages}":
                expanded.extend(sorted({"./" + str(Path(p).parent) for p in paths if p.endswith(".go")}))
                if not any(p.endswith(".go") for p in paths) and reason is None:
                    raise ValueError("Focused Go tests require explicit changed Go files")
            else:
                expanded.append(argument.replace("{python}", sys.executable).replace(
                    "{quality_root}", str(Path(__file__).resolve().parents[1])))
        result.append({**check, "argv": expanded, "selected": reason is None, "reason": reason})
    return {"route": selected, "checks": result}


def verify(store, config, paths, risk="low", task_type="implementation", family=None,
           allow_heavy=False, allow_network=False, only=None, diagnostic_budget=2000):
    if not 300 <= diagnostic_budget <= 2000:
        raise ValueError("Diagnostic budget must be 300–2000 tokens")
    planned = plan(config, paths, risk, task_type, family)
    if only and not set(only) <= {c["id"] for c in planned["checks"]}:
        raise ValueError("Unknown requested check")
    started = time.monotonic()
    results = []
    for check in planned["checks"]:
        base = {"id": check["id"], "required": check.get("required", True)}
        if not check["selected"]:
            results.append({**base, "status": "not_applicable", "reason": check["reason"]})
            continue
        if only and check["id"] not in only:
            results.append({**base, "status": "not_run", "reason": "not selected by --only"})
            continue
        if check.get("tier", "fast") == "heavy" and not allow_heavy:
            results.append({**base, "status": "blocked", "reason": "requires --allow-heavy"})
            continue
        if check.get("network", False) and not allow_network:
            results.append({**base, "status": "blocked", "reason": "requires --allow-network"})
            continue
        argv = check["argv"]
        executable = shutil.which(argv[0]) if "/" not in argv[0] else None
        if "/" in argv[0]:
            candidate = Path(argv[0]) if Path(argv[0]).is_absolute() else store.root / argv[0]
            # Absolute executables such as the selected Python are explicit config authority.
            executable = str(candidate) if candidate.is_file() else None
        if not executable:
            results.append({**base, "status": "missing_tool", "reason": argv[0]})
            continue
        timeout = check.get("timeout", 120)
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 3600:
            raise ValueError("Check timeout must be 0–3600 seconds")
        cache_key = None
        if check.get("cache", False):
            if not check.get("complete_inputs") or not check.get("inputs"):
                raise ValueError("Cached checks require complete_inputs=true and explicit versioned inputs")
            versions = [(p, read_source(store.root, p)["sha256"]) for p in check["inputs"]]
            stat = Path(executable).stat()
            cache_key = [check, versions, executable, stat.st_mtime_ns, stat.st_size]
            cached = cache_get(store, "checks", cache_key, ttl=3600)
            if cached:
                results.append({**base, "status": "passed", "cached": True, "evidence": cached})
                continue
        lock = resource_lock(store) if check.get("tier", "fast") == "heavy" else contextlib.nullcontext()
        try:
            with lock:
                limits = config.get("heavy_limits") if check.get("tier", "fast") == "heavy" else None
                executed = argv
                if limits:
                    cpu, memory = limits.get("cpu_percent"), limits.get("memory_mb")
                    if type(cpu) is not int or not 1 <= cpu <= 200 or type(memory) is not int or not 128 <= memory <= 8192:
                        raise ValueError("Heavy limits require CPU 1–200 percent and memory 128–8192 MiB")
                    executed = ["systemd-run", "--user", "--scope", "--quiet",
                                f"--property=CPUQuota={cpu}%", f"--property=MemoryMax={memory}M",
                                "--property=TasksMax=128", "nice", "-n", "10", *argv]
                captured = output.run(store, executed, timeout=timeout, preview_chars=1200)
            status = "timed_out" if captured["timed_out"] else "passed" if captured["exit_code"] == 0 else "failed"
            record = {**base, "status": status, "exit_code": captured["exit_code"], "log": captured["log"],
                      "diagnostic": captured["preview"] if status != "passed" else None}
        except (OSError, ValueError) as exc:
            record = {**base, "status": "blocked", "reason": str(exc)}
        if cache_key and record["status"] == "passed":
            cache_put(store, "checks", cache_key, {"log": record["log"], "inputs": versions})
        results.append(record)
    required = [r for r in results if r["required"] and r["status"] != "not_applicable"]
    status = "passed" if required and all(r["status"] == "passed" for r in required) else "incomplete"
    if any(r["status"] in {"failed", "timed_out"} for r in required):
        status = "failed"
    report = {"version": 1, "status": status, "results": results,
              "config_hash": digest(encode(config).encode()), "paths": paths,
              "elapsed_seconds": round(time.monotonic() - started, 3), "route": planned["route"]}
    filename = store.directory / ("quality-report-" + uuid.uuid4().hex + ".json")
    with filename.open("x") as stream:
        filename.chmod(0o600)
        stream.write(encode(report) + "\n")
    summary = {"status": status, "report": str(filename), "checks": [
        {k: v for k, v in r.items() if k not in {"diagnostic", "evidence"}} for r in results],
        "diagnostics": [], "diagnostics_omitted": 0}
    for result in results:
        if result.get("diagnostic"):
            summary["diagnostics"].append({"check": result["id"], "text": result["diagnostic"]})
            if packing.estimate(encode(summary)) > diagnostic_budget:
                summary["diagnostics"].pop()
                summary["diagnostics_omitted"] += 1
    if packing.estimate(encode(summary)) > diagnostic_budget:
        summary["checks"] = {state: sum(r["status"] == state for r in results)
                             for state in sorted({r["status"] for r in results})}
    return summary


def compare_performance(current, baseline, budgets):
    """Compare supplied measured metrics; missing/noisy evidence never becomes a pass."""
    results = []
    for name, rules in budgets.items():
        if not isinstance(rules, dict) or not ({"maximum", "regression_percent"} & set(rules)):
            raise ValueError("Each performance metric needs an explicit limit")
        for limit in rules.values():
            if not isinstance(limit, (int, float)) or isinstance(limit, bool) or not math.isfinite(limit) or limit < 0:
                raise ValueError("Performance limits must be finite nonnegative numbers")
        value = current.get(name)
        old = baseline.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            results.append({"metric": name, "status": "missing"})
            continue
        failures = []
        if "maximum" in rules and value > rules["maximum"]:
            failures.append("absolute budget exceeded")
        if "regression_percent" in rules:
            if not isinstance(old, (int, float)) or isinstance(old, bool) or not math.isfinite(old) or old <= 0:
                failures.append("positive baseline required")
            elif (value / old - 1) * 100 > rules["regression_percent"]:
                failures.append("regression budget exceeded")
        results.append({"metric": name, "status": "failed" if failures else "passed",
                        "value": value, "baseline": old, "failures": failures})
    return {"status": "passed" if results and all(r["status"] == "passed" for r in results) else "failed",
            "metrics": results, "notice": "Use comparable environments and repeated measurements; this is not a statistical significance test."}
