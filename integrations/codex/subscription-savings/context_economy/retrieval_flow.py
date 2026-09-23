"""Local-first retrieval and incremental indexing with explicit remote escalation."""

from argparse import Namespace

from . import quality_openrouter, quality_providers, retrieval
from .common import read_source
from .quality_common import cache_get, cache_put, resource_lock, sources


def update_index(store, selected):
    key = sorted(set(selected))
    saved = cache_get(store, "index-manifest-v2", key, ttl=365 * 86400)
    previous = saved["files"] if saved else {}
    # Deleted explicitly selected files are valid only when previously indexed.
    existing = []
    for spec in selected:
        if (store.root / spec).exists():
            existing.append(spec)
        elif saved is None or spec not in saved["selected"]:
            raise ValueError(f"Missing selected source that was never indexed: {spec}")
    pool = sources(store.root, existing, allow_empty=True) if existing else {}
    current = {path: source["sha256"] for path, source in pool.items()}
    changed = sorted(path for path, sha in current.items() if previous.get(path) != sha)
    removed = sorted(set(previous) - set(current))
    # ast_map's versioned cache reparses only changed content or parser versions.
    index = retrieval.ast_map(store, existing) if pool else {"files": [], "cache_hits": 0}
    cache_put(store, "index-manifest-v2", key, {"files": current, "selected": key})
    return {"indexed_files": len(index["files"]), "changed": changed, "removed": removed,
            "unchanged": sorted(set(current) - set(changed)), "cache_hits": index["cache_hits"],
            "notice": "Only current selected source enters retrieval; removed vectors are never candidates."}


def definition(store, source, expected_sha, maximum_bytes=16000):
    """Return exact selected source, refusing stale provenance or silent truncation."""
    selected = read_source(store.root, source)
    full = read_source(store.root, selected["path"])
    if full["sha256"] != expected_sha:
        raise ValueError("Source changed since retrieval; refresh provenance before reading")
    if len(selected["text"].encode()) > maximum_bytes:
        raise ValueError("Definition exceeds output budget; select an explicit smaller range")
    return {**selected, "file_sha256": full["sha256"], "complete_requested_range": True}


def rerank(store, args, matches):
    provider = quality_providers.provider_config(store, args, "rerank")
    if provider.get("backend") != "openrouter":
        raise ValueError("The retrieval flow requires native OpenRouter rerank")
    payload = {"operation": "rerank", "query": args.query, "revision": provider["revision"],
               "candidates": matches, "max_results": args.limit}
    quality_openrouter.validate_input(payload)
    key = [provider, payload]
    result = cache_get(store, "flow-rerank", key)
    if result is not None:
        return {**result, "cached_usage": result.get("usage"), "usage": None, "openrouter_calls": 0}
    if not args.allow_remote:
        raise ValueError("Rerank cache miss; explicitly authorize --allow-remote")
    with resource_lock(store, "network"):
        result = quality_providers.rank_response(payload, quality_openrouter.request(payload, provider), "rerank")
        cache_put(store, "flow-rerank", key, result)
    return {**result, "openrouter_calls": 1}


def retrieve(store, args):
    if not args.query.strip() or len(args.query) > 1000 or not 1 <= args.limit <= 5:
        raise ValueError("Retrieval needs a bounded query and 1–5 results")
    pool = sources(store.root, args.source, maximum=30)
    local = []
    for path, source in pool.items():
        for chunk in retrieval.definition_snippets(source["text"], path, args.query, store):
            if chunk["score"] <= 0:
                continue
            spec = f"{path}:{chunk['start']}:{chunk['end']}"
            local.append({**chunk, "id": spec, "source": spec, "path": path, "sha256": source["sha256"]})
    local.sort(key=lambda item: (-item["score"], item["id"]))
    exact = [item for item in local if args.symbol and item.get("symbol") == args.symbol]
    trace = [{"stage": "local", "candidates": len(local), "exact_symbol_matches": len(exact)}]
    if exact or not args.semantic_fallback:
        return {"matches": (exact or local)[:args.limit], "trace": trace, "openrouter_calls": 0,
                "reason": "exact symbol found" if exact else "local results; semantic fallback not requested"}
    if not args.evidence_gap.strip():
        raise ValueError("Explain the unresolved local evidence gap before semantic fallback")
    semantic_args = Namespace(**{**vars(args), "command": "semantic-search", "library": None,
                                "library_version": None, "preview_remote": args.preview_remote})
    semantic = quality_providers.run(store, semantic_args)
    if args.preview_remote:
        return {"local_matches": local[:args.limit], "trace": trace, "remote_preview": semantic, "sent": False}
    trace.append({"stage": "embedding", "model": semantic.get("model"), "usage": semantic.get("usage"),
                  "cache_hit": semantic.get("cache_hit"), "embedding_cache_hits": semantic.get("embedding_cache_hits", 0)})
    # IDs/text always come from the selected source, never model-generated code.
    ranked = rerank(store, args, semantic["matches"])
    trace.append({"stage": "rerank", "model": ranked.get("model"), "usage": ranked.get("usage"),
                  "openrouter_calls": ranked["openrouter_calls"]})
    for item in ranked["matches"]:
        if read_source(store.root, item["source"].rsplit(":", 2)[0])["sha256"] != item["sha256"]:
            raise ValueError("Selected code changed during retrieval; results are stale")
    return {"matches": ranked["matches"], "trace": trace,
            "openrouter_calls": semantic.get("openrouter_calls", 0) + ranked["openrouter_calls"],
            "notice": "Ranking is advisory; inspect source compatibility and related tests."}
