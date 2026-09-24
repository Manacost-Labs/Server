"""Small labeled retrieval suites against real project files; no task-savings claims."""

import json
from argparse import Namespace
from pathlib import Path

from . import retrieval_flow
from .common import read_source

SUITES = {
    "hearthpulse": [
        {"id": "public-profile-link", "query": "canonical numeric public profile link",
         "source": ["src/modules/identity/model/publicProfilePath.ts", "src/publicResourceUrl.ts"],
         "expected_path": "src/modules/identity/model/publicProfilePath.ts"},
        {"id": "client-route-meta", "query": "preserve initial server metadata during client route change",
         "source": ["src/app/routing/routeResolution.ts", "src/modules/identity/model/publicProfilePath.ts"],
         "expected_path": "src/app/routing/routeResolution.ts"},
    ],
    "hs-manacost": [
        {"id": "s3-image-path", "query": "reject invalid relative image path outside base directory",
         "source": ["wordpress/mu-plugins/hs-manacost-s3-offload/src/PathPolicy.php",
                    "wordpress/mu-plugins/hs-manacost-s3-offload/src/Hydrator.php"],
         "expected_path": "wordpress/mu-plugins/hs-manacost-s3-offload/src/PathPolicy.php"},
        {"id": "s3-image-restore", "query": "restore image from storage with downloader",
         "source": ["wordpress/mu-plugins/hs-manacost-s3-offload/src/PathPolicy.php",
                    "wordpress/mu-plugins/hs-manacost-s3-offload/src/Hydrator.php"],
         "expected_path": "wordpress/mu-plugins/hs-manacost-s3-offload/src/Hydrator.php"},
    ],
}


def load_manifest(store, name):
    """Load a small, versioned labeled set from the project that owns the code."""
    source = read_source(store.root, name)
    if len(source["text"].encode()) > 32768:
        raise ValueError("Evaluation manifest exceeds 32 KiB")
    document = json.loads(source["text"])
    if not isinstance(document, dict) or set(document) != {"version", "cases"} or document["version"] != 1:
        raise ValueError("Evaluation manifest must be a version 1 object with cases")
    return document["cases"], source["sha256"]


def select_cases(cases, identifiers):
    if not identifiers:
        return cases
    if len(identifiers) > 20 or len(set(identifiers)) != len(identifiers):
        raise ValueError("Select at most 20 distinct case IDs")
    available = {case.get("id") for case in cases if isinstance(case, dict)}
    if not set(identifiers) <= available:
        raise ValueError("Unknown evaluation case ID")
    return [case for case in cases if case["id"] in identifiers]


def evaluate(store, cases, semantic=False, limit=3):
    if not isinstance(cases, list) or not 1 <= len(cases) <= 20 or not 1 <= limit <= 5:
        raise ValueError("Evaluation requires 1–20 labeled cases and 1–5 results")
    rows = []
    calls = 0
    identifiers = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "query", "source", "expected_path"}:
            raise ValueError("Case needs id, query, source and expected_path only")
        identifier, query, source, expected = (case[name] for name in
                                               ("id", "query", "source", "expected_path"))
        if (not isinstance(identifier, str) or not 1 <= len(identifier) <= 80 or identifier in identifiers
                or not isinstance(query, str)):
            raise ValueError("Case id/query must be bounded strings")
        identifiers.add(identifier)
        if not isinstance(source, list) or not 1 <= len(source) <= 20 or not all(isinstance(s, str) for s in source):
            raise ValueError("Case source must select 1–20 paths")
        if expected is not None and (not isinstance(expected, str) or Path(expected).is_absolute()
                                     or ".." in Path(expected).parts or not any(
                expected == spec or expected.startswith(spec.rstrip("/") + "/") for spec in source)):
            raise ValueError("Expected path must be within selected project source")
        args = Namespace(query=query, source=source, limit=limit, symbol=None, semantic_fallback=semantic,
                         allow_remote=semantic, preview_remote=False, evidence_gap="Evaluate labeled retrieval gap",
                         config=".ai/manacost-quality.json")
        result = retrieval_flow.retrieve(store, args)
        found = [match["path"] if "path" in match else match["source"].rsplit(":", 2)[0]
                 for match in result["matches"]]
        rank = found.index(expected) + 1 if expected is not None and expected in found else None
        calls += result["openrouter_calls"]
        rows.append({"id": identifier, "rank": rank, "returned": len(found),
                     "expected_absent": expected is None,
                     "correct": not found if expected is None else rank is not None,
                     "openrouter_calls": result["openrouter_calls"]})
    positives = [row for row in rows if not row["expected_absent"]]
    negatives = [row for row in rows if row["expected_absent"]]
    return {"cases": rows, "count": len(rows), "limit": limit,
            "positive_cases": len(positives), "negative_cases": len(negatives),
            "hit_at_k": sum(row["rank"] is not None for row in positives) / len(positives) if positives else None,
            "mrr_at_k": sum(1 / row["rank"] for row in positives if row["rank"] is not None) /
            len(positives) if positives else None,
            "negative_rejection_rate": sum(row["correct"] for row in negatives) / len(negatives) if negatives else None,
            "openrouter_calls": calls, "mode": "embedding-rerank" if semantic else "local",
            "notice": "Ranks are among returned snippets, not all files. No end-to-end task savings inferred."}
