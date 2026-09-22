"""Reusable, source-versioned reference drafts; independent of a caller's task."""

import json
import math
import time
from pathlib import Path

from . import assist, facts, meter, packing, remote
from .common import digest, encode, read_source


def run(store, args):
    if not 1 <= len(args.source) <= 6 or args.purpose not in ("context", "memory", "documentation"):
        raise ValueError("Choose 1–6 sources and a reference purpose")
    if not 100 <= args.budget <= 12000:
        raise ValueError("Brief output budget must be in [100,12000]")
    minimum = getattr(args, "min_reduction", .15)
    if not math.isfinite(minimum) or not .05 <= minimum <= .9:
        raise ValueError("Minimum complete-packet reduction must be in [0.05,0.9]")
    if args.allow_remote and (not 0 < args.daily_budget_usd <= 1 or not 0 < args.api_timeout <= 30):
        raise ValueError("Brief requires a budget in (0,$1] and timeout in (0,30]")
    sources = [read_source(store.root, s) for s in dict.fromkeys(args.source)]
    if any(Path(s["path"]).name.upper() in {"AGENTS.MD", "CLAUDE.MD", "SKILL.MD"} for s in sources):
        raise ValueError("Instruction files must remain verbatim; use pack --required")
    if sum(len(s["text"].encode()) for s in sources) > 24000:
        raise ValueError("Selected brief inputs exceed 24 KB; narrow fragments")
    critical, critical_source = facts.load(store.root, getattr(args, "facts", None),
                                           {str(i): s for i, s in enumerate(sources)},
                                           {"context": sources, "required_sources": []})
    requests = []
    for source in sources:
        state = {"task": {"goal": "Prepare a reusable source reference, not an answer to a particular task",
                          "criteria": ["Quote observable contracts and error conditions", "Do not invent behavior"],
                          "constraints": ["Interpretations are drafts; future tasks must verify applicability"]},
                 "purpose": args.purpose, "sources": {"s0": source["text"]}}
        assist.check_remote_state(state)
        payload = assist.payloads(state)["gemma"]
        key = digest(encode(["file-brief-v1", source["source"], source["sha256"], args.purpose, payload]).encode())
        requests.append((source, key, payload))
    if args.preview_remote:
        return {"preview_only": True, "endpoint": remote.ENDPOINTS["gemma"],
                "requests": [payload for _, _, payload in requests]}
    store.db.execute("CREATE TABLE IF NOT EXISTS file_briefs (id TEXT PRIMARY KEY, created REAL, body TEXT)")
    store.db.commit()
    ledger = None
    results = []
    try:
        for source, key, payload in requests:
            candidates = {"s0": source}
            row = store.db.execute("SELECT body FROM file_briefs WHERE id=? AND created>?",
                                   (key, time.time() - 30 * 86400)).fetchone()
            draft = None
            small = len(source["text"].encode()) < 600
            usage = {"status": "skipped-small-source" if small else "local", "request_cost_usd": 0}
            if row:
                try:
                    # Revalidate exact evidence against the current source even on cache hits.
                    cached = json.loads(row[0])
                    draft = assist.validate_gemma(cached, candidates)
                    usage["status"] = "file_cache"
                    meter.remote_event(store, "cache")
                except (ValueError, TypeError, KeyError):
                    pass
            if draft is None and args.allow_remote and not small:
                ledger = ledger or remote.Ledger()
                validated_response = []

                def validate(response):
                    result = assist.validate_gemma(response, candidates)
                    validated_response.append(response)
                    return result

                try:
                    draft, usage = remote.request(store, ledger, "gemma", payload, args.daily_budget_usd,
                                                   validate, args.api_timeout)
                    with store.db:
                        store.db.execute("DELETE FROM file_briefs WHERE created < ?", (time.time() - 30 * 86400,))
                        store.db.execute("INSERT OR REPLACE INTO file_briefs VALUES (?,?,?)",
                                         (key, time.time(), encode(validated_response[-1])))
                except (OSError, ValueError, TypeError, KeyError):
                    usage = {"status": "fallback", "request_cost_usd": None}
            # Omitted mandatory evidence restores this entire original fragment.
            if draft and any(f["source"] == source["source"] and
                             not any(f["quote"] in item["quote"] for item in draft["items"]) for f in critical):
                draft = None
            results.append({"source": source["source"], "sha256": source["sha256"], "usage": usage,
                            "draft": draft, "original": source["text"] if draft is None else None})
    finally:
        if ledger:
            ledger.close()
    if any(read_source(store.root, s["source"])["sha256"] != s["sha256"] for s in sources):
        raise ValueError("Brief source changed; rerun before using the result")
    if critical_source and read_source(store.root, critical_source["source"])["sha256"] != critical_source["sha256"]:
        raise ValueError("Critical evidence changed; rerun")
    result = {"purpose": args.purpose, "references": results,
              "reduction": {"applied": True, "minimum_fraction": minimum, "basis": "complete-packet-utf8-bytes"},
              "notice": "Reusable reference drafts, not verified memory or task-specific answers. "
                        "Check applicability and critical facts; open original sources when uncertain."}
    original = dict(result, references=[dict(r, draft=None, original=s["text"]) for r, s in zip(results, sources)],
                    reduction=dict(result["reduction"], applied=False))
    if (not any(r["draft"] for r in results) or
            len(encode(result).encode()) > len(encode(original).encode()) * (1 - minimum)):
        result = original
    if packing.estimate(encode(result)) > args.budget:
        raise ValueError("Brief output exceeds budget; narrow sources or increase the output budget")
    return result
