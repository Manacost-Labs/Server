"""Small labeled retrieval suites against real project files; no task-savings claims."""

from argparse import Namespace
from pathlib import Path

from . import retrieval_flow

SUITES = {
    "hearthpulse": [
        {"id": "public-profile-link", "query": "canonical numeric public profile link",
         "source": ["src/publicProfilePath.ts", "src/publicResourceUrl.ts"],
         "expected_path": "src/publicProfilePath.ts"},
        {"id": "client-route-meta", "query": "preserve initial server metadata during client route change",
         "source": ["src/routing/clientRouteResolution.ts", "src/publicProfilePath.ts"],
         "expected_path": "src/routing/clientRouteResolution.ts"},
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


def evaluate(store, cases, semantic=False, limit=3):
    if not isinstance(cases, list) or not 1 <= len(cases) <= 20 or not 1 <= limit <= 5:
        raise ValueError("Evaluation requires 1–20 labeled cases and 1–5 results")
    rows = []
    calls = 0
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "query", "source", "expected_path"}:
            raise ValueError("Case needs id, query, source and expected_path only")
        identifier, query, source, expected = (case[name] for name in
                                               ("id", "query", "source", "expected_path"))
        if not isinstance(identifier, str) or not 1 <= len(identifier) <= 80 or not isinstance(query, str):
            raise ValueError("Case id/query must be bounded strings")
        if not isinstance(source, list) or not 1 <= len(source) <= 20 or not all(isinstance(s, str) for s in source):
            raise ValueError("Case source must select 1–20 paths")
        if not isinstance(expected, str) or Path(expected).is_absolute() or ".." in Path(expected).parts or not any(
                expected == spec or expected.startswith(spec.rstrip("/") + "/") for spec in source):
            raise ValueError("Expected path must be within selected project source")
        args = Namespace(query=query, source=source, limit=limit, symbol=None, semantic_fallback=semantic,
                         allow_remote=semantic, preview_remote=False, evidence_gap="Evaluate labeled retrieval gap",
                         config=".ai/manacost-quality.json")
        result = retrieval_flow.retrieve(store, args)
        found = [match["path"] if "path" in match else match["source"].rsplit(":", 2)[0]
                 for match in result["matches"]]
        rank = found.index(expected) + 1 if expected in found else None
        calls += result["openrouter_calls"]
        rows.append({"id": identifier, "rank": rank, "returned": len(found),
                     "openrouter_calls": result["openrouter_calls"]})
    return {"cases": rows, "count": len(rows), "limit": limit,
            "hit_at_k": sum(row["rank"] is not None for row in rows) / len(rows),
            "mrr_at_k": sum(1 / row["rank"] for row in rows if row["rank"] is not None) / len(rows),
            "openrouter_calls": calls, "mode": "embedding-rerank" if semantic else "local",
            "notice": "Labeled file retrieval only; no end-to-end task quality or token savings inferred."}
