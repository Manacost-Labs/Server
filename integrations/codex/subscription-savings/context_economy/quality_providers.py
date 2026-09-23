"""Explicit docs/GitHub adapters and bounded pluggable embedding/reranking backends.

No provider is called as a side effect of ordinary local retrieval. Provider output
is untrusted reference data and never authorizes shell commands or instructions.
"""

import base64
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

from . import meter, quality_openrouter, retrieval
from .common import digest, encode
from .quality_common import cache_get, cache_put, load_config, resource_lock, sources


def capture(argv, payload=None, maximum=256000):
    if not shutil.which(argv[0]):
        raise ValueError(f"Missing provider executable: {argv[0]}")
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        completed = subprocess.run(argv, input=encode(payload).encode() if payload is not None else None,
                                   stdout=out, stderr=err, timeout=30)
        if completed.returncode:
            raise ValueError(f"Provider {argv[0]} failed with exit code {completed.returncode}; check its local configuration")
        out.seek(0)
        raw = out.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("Provider output exceeded the bounded response limit")
    return json.loads(raw)


def docs(args):
    if not args.library or not args.library_version:
        raise ValueError("Docs require --library (Context7 ID) and --library-version matching the project")
    if not re.fullmatch(r"/[\w.-]+/[\w./-]+", args.library) or len(args.library) > 160:
        raise ValueError("Invalid Context7 library ID")
    query = f"For version {args.library_version}: {args.query}"
    response = capture(["ctx7", "docs", args.library, query, "--json"])
    if not isinstance(response, dict):
        raise ValueError("Invalid Context7 response")
    excerpts = []
    for item in response.get("codeSnippets", [])[:args.limit]:
        excerpts.append({"source": item.get("codeId"), "title": item.get("codeTitle"),
                         "text": "\n".join(c.get("code", "") for c in item.get("codeList", []))[:2200]})
    for item in response.get("infoSnippets", [])[:max(0, args.limit - len(excerpts))]:
        excerpts.append({"source": item.get("pageId"), "text": item.get("content", "")[:2200]})
    if not excerpts:
        raise ValueError("Context7 returned no documentation evidence")
    return {"library": args.library, "requested_version": args.library_version, "excerpts": excerpts,
            "version_verified": False,
            "notice": "Check cited documentation against the installed version; a version in a query is not version proof."}


def references(args, store=None):
    pool_limit = min(9, max(4, args.limit * 3))
    searched = capture(["gh", "api", "-X", "GET", "search/code", "-f", "q=" + args.query,
                        "-f", "per_page=" + str(pool_limit)])
    results, rejected, repositories = [], [], {}
    query = re.sub(r'\b(?:repo|org|user|path|language|filename|extension|in):(?:"[^"]+"|\S+)', "", args.query)
    extensions = {".py", ".go", ".js", ".jsx", ".ts", ".tsx", ".php", ".rs", ".java", ".c", ".cpp", ".h", ".rb", ".lua", ".sh", ".css"}
    started = time.monotonic()
    for item in searched.get("items", [])[:pool_limit]:
        if time.monotonic() - started > 30:
            rejected.append({"reason": "reference lookup time budget reached"})
            break
        repo = item.get("repository", {}).get("full_name", "")
        path = item.get("path", "")
        if retrieval.is_test(path) and not getattr(args, "include_tests", False):
            rejected.append({"repository": repo, "path": path, "reason": "test source excluded; use --include-tests explicitly"})
            continue
        if (not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or not path or ".." in path.split("/")
                or Path(path).suffix not in extensions):
            rejected.append({"repository": repo, "path": path, "reason": "not a supported code path"})
            continue
        metadata = repositories.get(repo, {}).get("metadata")
        if metadata is None:
            metadata = capture(["gh", "api", "repos/" + repo, "--jq",
                                "{default_branch,license,archived,pushed_at,stargazers_count}"])
            repositories[repo] = {"metadata": metadata}
        license_id = (metadata.get("license") or {}).get("spdx_id")
        if metadata.get("archived") or not license_id or license_id == "NOASSERTION":
            rejected.append({"repository": repo, "reason": "archived or unverified license metadata"})
            continue
        branch = quote(metadata["default_branch"], safe="")
        commit = repositories[repo].get("commit")
        if commit is None:
            commit = capture(["gh", "api", f"repos/{repo}/commits/{branch}", "--jq", "{sha}"])["sha"]
            repositories[repo]["commit"] = commit
        if not re.fullmatch(r"[a-fA-F0-9]{40,64}", commit):
            raise ValueError("Invalid reference revision")
        try:
            file = capture(["gh", "api", f"repos/{repo}/contents/{quote(path, safe='/')}?ref={commit}"])
        except ValueError:
            rejected.append({"repository": repo, "path": path, "reason": "source fetch failed or exceeded output budget"})
            continue
        if file.get("type") != "file" or file.get("encoding") != "base64" or file.get("size", 1_000_001) > 100000:
            rejected.append({"repository": repo, "path": path, "reason": "not a bounded text source"})
            continue
        try:
            raw = base64.b64decode("".join(file["content"].split()), validate=True)
            # Git's content identifier uses SHA-1; this is not a signature/trust check.
            blob = hashlib.sha1(  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
                b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False).hexdigest()
            if len(raw) != file["size"] or blob != file.get("sha") or b"\0" in raw:
                raise ValueError("Git blob/size mismatch or binary source")
            snippets = retrieval.definition_snippets(raw.decode("utf-8"), path, query, store, maximum_bytes=3000)
            if not snippets or (query.strip() and snippets[0]["score"] == 0):
                raise ValueError("No matching implementation excerpt")
        except (ValueError, UnicodeError) as exc:
            rejected.append({"repository": repo, "path": path, "reason": str(exc)[:100]})
            continue
        best = snippets[0]
        if getattr(args, "full_definition", False):
            if "definition_start" not in best:
                rejected.append({"repository": repo, "path": path, "reason": "complete AST definition unavailable"})
                continue
            complete = "\n".join(raw.decode("utf-8").splitlines()[best["definition_start"] - 1:best["definition_end"]])
            if len(complete.encode()) > 16000:
                rejected.append({"repository": repo, "path": path, "reason": "complete definition exceeds 16 KB; request an excerpt"})
                continue
            best = {**best, "start": best["definition_start"], "end": best["definition_end"],
                    "text": complete, "complete_definition": True}
        start, end, excerpt = best["start"], best["end"], best["text"]
        results.append({"repository": repo, "path": path, "commit": commit, "sha256": digest(raw),
                        "start": start, "end": end, "license": license_id, "lexical_score": best["score"],
                        "blob_sha": blob, "blob_verified": True, "provenance": "GitHub contents API at pinned commit",
                        "test_source": retrieval.is_test(path),
                        **{key: best[key] for key in ("symbol", "definition_start", "definition_end",
                                                     "selection_kind", "complete_definition") if key in best},
                        "search_matches_revision": item.get("sha") == blob,
                        "pushed_at": metadata.get("pushed_at"), "stars": metadata.get("stargazers_count"),
                        "url": f"https://github.com/{repo}/blob/{commit}/{quote(path)}#L{start}-L{end}",
                        "text": excerpt, "tests_verified": False, "compatibility_verified": False})
    results.sort(key=lambda item: (-item["lexical_score"], item["url"]))
    selected = results if getattr(args, "rerank_references", False) else results[:args.limit]
    return {"references": selected, "rejected": rejected, "candidates_found": len(results),
            "notice": "Metadata filters are not a correctness/security assessment. Review compatibility, tests and license before reuse."}


def provider_config(store, args, operation):
    path = store.root / args.config
    config = load_config(store.root, args.config) if path.exists() or args.config != ".ai/manacost-quality.json" else {}
    configured = config.get("providers", {}).get(operation)
    if configured is None:
        return quality_openrouter.defaults(operation)
    if not isinstance(configured, dict):
        raise ValueError("Provider configuration must be an object")
    if configured.get("backend") == "openrouter":
        return {**quality_openrouter.defaults(operation), **configured}
    return configured


def backend_request(store, args, config):
    provider = config.get("providers", {}).get(args.command)
    if not isinstance(provider, dict):
        raise ValueError("Configure an explicit versioned semantic/rerank provider")
    native = provider.get("backend") == "openrouter"
    argv = (["openrouter", provider["model"], str(provider.get("dimensions", 1024))]
            if native else provider.get("argv"))
    if not isinstance(argv, list) or not argv or len(argv) > 20 or any(not isinstance(x, str) or not x for x in argv):
        raise ValueError("Provider requires an explicit argv array or native OpenRouter backend")
    if not provider.get("revision"):
        raise ValueError("Provider requires a pinned model/backend revision for cache validity")
    pool = sources(store.root, args.source, maximum=30)
    candidates = []
    for path, source in pool.items():
        for chunk in retrieval.definition_snippets(source["text"], path, args.query, store):
            reference = f"{path}:{chunk['start']}:{chunk['end']}"
            candidates.append({"id": reference, "source": reference, "sha256": source["sha256"],
                               "text": chunk["text"], "lexical_score": chunk["score"],
                               **{key: chunk[key] for key in ("symbol", "selection_kind", "complete_definition") if key in chunk}})
    candidates.sort(key=lambda item: (-item["lexical_score"], item["id"]))
    available = len(candidates)
    payload = {"operation": args.command, "query": args.query, "revision": provider["revision"],
               "candidates": candidates[:30], "max_results": args.limit,
               "selection": {"available_chunks": available, "omitted_chunks": 0}}
    ceiling_bytes = 23000 if native else 63000
    while payload["candidates"] and len(encode(payload).encode()) > ceiling_bytes:
        payload["candidates"].pop()
    payload["selection"]["omitted_chunks"] = available - len(payload["candidates"])
    if not payload["candidates"]:
        raise ValueError("No source chunks fit the provider budget")
    # Backend operators enforce the declared charge ceiling. No silent unknown-price calls.
    if provider.get("network", True):
        ceiling = provider.get("max_cost_usd")
        if not isinstance(ceiling, (int, float)) or isinstance(ceiling, bool) or not math.isfinite(ceiling) or not 0 < ceiling <= 1:
            raise ValueError("Remote backend requires an explicit per-call ceiling in (0,1] USD")
        payload["max_cost_usd"] = ceiling
    return argv, payload


def cosine(left, right):
    if not isinstance(left, list) or not isinstance(right, list) or not 1 <= len(left) == len(right) <= 4096:
        raise ValueError("Invalid embedding dimensions")
    if any(not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x) for x in left + right):
        raise ValueError("Embeddings must contain finite numbers")
    norm = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(x * x for x in right))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("Embedding has zero/invalid norm")
    return sum(a * b for a, b in zip(left, right)) / norm


def rank_response(payload, response, operation):
    if not isinstance(response, dict) or not isinstance(response.get("candidates"), list):
        raise ValueError("Provider must return candidate evidence")
    expected = {c["id"]: c for c in payload["candidates"]}
    received = response["candidates"]
    ids = [c.get("id") for c in received]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise ValueError("Provider omitted, duplicated or invented candidate IDs")
    ranked = []
    for candidate in received:
        score = (cosine(response.get("query_embedding"), candidate.get("embedding"))
                 if operation == "semantic-search" else candidate.get("score"))
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score):
            raise ValueError("Provider scores must be finite")
        ranked.append({**expected[candidate["id"]], "score": score})
    ranked.sort(key=lambda x: (-x["score"], x["id"]))
    return {"matches": ranked[:payload["max_results"]], "usage": response.get("usage"),
            **{key: response[key] for key in ("provider", "model", "reported_model") if key in response},
            "notice": "Ranking is advisory; exact source hashes must still verify before use."}


def reserve_call(store, operation, ceiling=0, daily_budget=0, call_limit=10):
    if not isinstance(call_limit, int) or not 1 <= call_limit <= 30:
        raise ValueError("Provider daily call limit must be 1–30")
    if not isinstance(daily_budget, (int, float)) or not math.isfinite(daily_budget) or not 0 <= daily_budget <= 10:
        raise ValueError("Provider daily budget must be explicitly bounded to 0–10 USD")
    store.db.execute("CREATE TABLE IF NOT EXISTS quality_provider_calls (created REAL, operation TEXT, reserved REAL)")
    now = time.time()
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        count, cost = store.db.execute("SELECT COUNT(*), COALESCE(SUM(reserved),0) FROM quality_provider_calls "
                                       "WHERE created>=? AND operation=?", (now - 86400, operation)).fetchone()
        if count >= call_limit or cost + ceiling > daily_budget + 1e-9:
            raise ValueError("Provider daily call/cost budget exhausted")
        store.db.execute("INSERT INTO quality_provider_calls VALUES(?,?,?)", (now, operation, ceiling))
        store.db.execute("DELETE FROM quality_provider_calls WHERE created<?", (now - 7 * 86400,))


def semantic_cached(store, argv, payload, fetch=None):
    # Embeddings are independent of the query. Pin backend, revision, source hash
    # and exact chunk; send only misses, then validate the full merged response.
    def key(candidate):
        return [argv, payload["revision"], candidate["sha256"], candidate["source"], candidate["text"]]

    hits, missing = [], []
    for candidate in payload["candidates"]:
        cached = cache_get(store, "embedding", key(candidate))
        if cached:
            hits.append({"id": candidate["id"], "embedding": cached["embedding"]})
        else:
            missing.append(candidate)
    request = {**payload, "candidates": missing}
    response = (fetch or capture)(argv, request)
    rank_response(request, response, "semantic-search")
    merged = {**response, "candidates": hits + response["candidates"]}
    result = rank_response(payload, merged, "semantic-search")
    by_id = {item["id"]: item for item in response["candidates"]}
    for candidate in missing:
        cache_put(store, "embedding", key(candidate), {"embedding": by_id[candidate["id"]]["embedding"]})
    return {**result, "embedding_cache_hits": len(hits)}


def rank_references(result, args, provider):
    if len(result["references"]) < 2:
        return {**result, "rerank": {"status": "not_needed", "reason": "fewer than two verified references"}}
    references = {item["url"]: item for item in result["references"]}
    payload = {"operation": "rerank", "query": args.query, "revision": provider["revision"],
               "max_results": args.limit, "candidates": [
                   {"id": item["url"], "text": item["text"]} for item in references.values()]}
    while len(encode(payload).encode()) > 23000 and len(payload["candidates"]) > args.limit:
        payload["candidates"].pop()
    ranked = rank_response(payload, quality_openrouter.request(payload, provider), "rerank")
    return {**result, "references": [{**references[item["id"]], "rerank_score": item["score"]} for item in ranked["matches"]],
            "rerank": {"status": "completed", "model": provider["model"], "usage": ranked.get("usage"),
                       "candidates": len(payload["candidates"])}}


def run(store, args):
    if not args.evidence_gap.strip() or len(args.evidence_gap) > 1000 or not args.query.strip() or len(args.query) > 1000:
        raise ValueError("Name the bounded query and unresolved local evidence gap")
    if not 1 <= args.limit <= (5 if args.command in {"semantic-search", "rerank"} else 3):
        raise ValueError("Provider result limit exceeded")
    payload = {"operation": args.command, "query": args.query, "library": args.library,
               "version": args.library_version, "limit": args.limit,
               "include_tests": getattr(args, "include_tests", False),
               "full_definition": getattr(args, "full_definition", False)}
    quality_openrouter.validate_input({"operation": "rerank", "query": args.query, "candidates": []})
    argv, provider = None, {}
    if args.command in {"semantic-search", "rerank"}:
        provider = provider_config(store, args, args.command)
        config = {"providers": {args.command: provider}}
        argv, payload = backend_request(store, args, config)
        if provider.get("backend") == "openrouter":
            quality_openrouter.validate_input(payload)
    rerank_refs = args.command == "reference-search" and getattr(args, "rerank_references", False)
    if rerank_refs:
        provider = provider_config(store, args, "rerank")
        if provider.get("backend") != "openrouter":
            raise ValueError("Reference reranking requires the native OpenRouter backend")
        payload["rerank_provider"] = provider
    if args.preview_remote:
        return {"preview": payload, "argv": argv, "sent": False}
    key = [argv, payload]
    cached = cache_get(store, "provider", key, ttl=86400)
    if cached:
        previous_usage = cached.pop("usage", None)
        if "rerank" in cached:
            cached["rerank"] = {**cached["rerank"], "cached_usage": cached["rerank"].get("usage"), "usage": None}
        return {**cached, "usage": None, "cached_usage": previous_usage, "cache_hit": True,
                "network_calls": 0, "openrouter_calls": 0, "call_cost_usd": 0}
    if not args.allow_remote:
        raise ValueError("Provider cache miss: inspect --preview-remote, then explicitly use --allow-remote")
    with resource_lock(store, "network"):
        native = provider.get("backend") == "openrouter"
        if not native or args.command == "reference-search":
            reserve_call(store, args.command, payload.get("max_cost_usd", 0), provider.get("daily_budget_usd", 0),
                         provider.get("calls_per_day", 10))
        fetch = (lambda _, request: quality_openrouter.request(request, provider)) if native else capture
        if args.command == "docs":
            result = docs(args)
        elif args.command == "reference-search":
            result = references(args, store)
            if rerank_refs:
                result = rank_references(result, args, provider)
        elif args.command == "semantic-search":
            result = semantic_cached(store, argv, payload, fetch)
        else:
            result = rank_response(payload, fetch(argv, payload), args.command)
        if "selection" in payload:
            result["selection"] = payload["selection"]
    result["openrouter_calls"] = int(native and (args.command in {"semantic-search", "rerank"}
                                     or result.get("rerank", {}).get("status") == "completed"))
    cache_put(store, "provider", key, result)
    meter.event(store, "retrieval", {"provider": args.command, "cache_hit": False,
                                     "usage": result.get("usage"), "candidates": len(payload.get("candidates", []))})
    return {**result, "cache_hit": False}
