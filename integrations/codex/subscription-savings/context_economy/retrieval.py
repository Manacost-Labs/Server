"""Incremental AST maps, scoped lexical retrieval, related tests and verifiable packs.

AST references are syntax candidates, never claims of a resolved compiler call graph.
"""

import json
import math
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from . import packing
from .common import digest, encode, read_source
from .quality_common import cache_get, cache_put, resource_lock, sources

LANGUAGES = {
    ".py": ("Python", ["function_definition", "class_definition"], ["call"],
            ["import_statement", "import_from_statement"]),
    ".go": ("Go", ["function_declaration", "method_declaration", "type_spec"],
            ["call_expression"], ["import_declaration"]),
    ".ts": ("TypeScript", ["function_declaration", "method_definition", "class_declaration",
                          "interface_declaration", "type_alias_declaration", "variable_declarator"],
            ["call_expression", "new_expression"], ["import_statement"]),
    ".tsx": ("Tsx", ["function_declaration", "method_definition", "class_declaration",
                     "interface_declaration", "variable_declarator"],
             ["call_expression", "new_expression", "jsx_opening_element", "jsx_self_closing_element"],
             ["import_statement"]),
    ".js": ("JavaScript", ["function_declaration", "method_definition", "class_declaration",
                           "variable_declarator"], ["call_expression", "new_expression"], ["import_statement"]),
    ".php": ("Php", ["function_definition", "method_declaration", "class_declaration",
                     "interface_declaration", "trait_declaration"],
             ["function_call_expression", "member_call_expression", "scoped_call_expression"],
             ["namespace_use_declaration"]),
}
LANGUAGES[".jsx"] = LANGUAGES[".js"]


def tokens(text):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return re.findall(r"[^\W_]+", text.casefold(), re.UNICODE)


def is_test(path):
    return bool(re.search(r"(^|[/_.-])(tests?|specs?)([/_.-]|$)|_test\.", path, re.I))


def chunks(text, query, maximum_bytes=1800):
    """Rank exact contiguous chunks across the whole file, including its tail."""
    terms = set(tokens(query))
    lines = text.splitlines()
    result, start = [], 0
    while start < len(lines):
        end, size = start, 0
        while end < len(lines) and end - start < 32:
            length = len(lines[end].encode()) + int(end > start)
            if size + length > maximum_bytes:
                break
            size += length
            end += 1
        if end == start:
            # Do not truncate a source line into a fictitious code snippet.
            raise ValueError("Source line exceeds retrieval chunk budget; choose a smaller source")
        excerpt = "\n".join(lines[start:end])
        if excerpt.strip():
            counts = Counter(tokens(excerpt))
            score = sum(1 + math.log1p(counts[term]) for term in terms if counts[term])
            result.append({"start": start + 1, "end": end, "text": excerpt, "score": score})
        start = end
    return sorted(result, key=lambda item: (-item["score"], item["start"]))


def _name(text, group):
    lines = text.strip().splitlines()
    if not lines:
        return ""
    first = lines[0]
    if group == "imports":
        return first[:200]
    if group == "references":
        parts = re.sub(r"^new\s+|^<", "", first.split("(")[0]).split()
        return parts[0][:160] if parts else ""
    match = re.search(r"\b(?:async\s+def|def|function|class|interface|trait|type)\s+([\w$]+)", first)
    if not match:
        match = re.search(r"\bfunc\s+(?:\([^)]*\)\s*)?([\w]+)", first)
    if not match:
        match = re.match(r"(?:public\s+|private\s+|static\s+|async\s+)*([\w$]+)", first)
    return match.group(1) if match else first[:120]


def parse_ast(path, source, tool, language):
    rules = []
    for group, kinds in zip(("symbols", "references", "imports"), language[1:]):
        for kind in kinds:
            rules.append(encode({"id": group + ":" + kind, "language": language[0], "severity": "hint",
                                 "message": group, "rule": {"kind": kind}}))
    with tempfile.TemporaryDirectory(prefix="quality-ast-") as directory:
        target = Path(directory) / ("source" + Path(path).suffix)
        target.write_text(source["text"])
        with tempfile.TemporaryFile() as stream:
            process = subprocess.run([tool, "scan", "--inline-rules", "\n---\n".join(rules),
                                      "--json=compact", "--threads", "1", str(target)],
                                     stdout=stream, stderr=subprocess.PIPE, timeout=20)
            if process.returncode != 0:
                raise ValueError(f"AST parser failed for {path}: {process.stderr.decode(errors='replace')[:400]}")
            stream.seek(0)
            raw = stream.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("AST output budget exceeded; narrow the file")
    item = {"path": path, "sha256": source["sha256"], "test": is_test(path),
            "symbols": [], "references": [], "imports": []}
    for node in json.loads(raw):
        group, kind = node["ruleId"].split(":", 1)
        name = _name(node["text"], group)
        if not name:
            continue
        item[group].append({"name": name, "kind": kind,
                            "start": node["range"]["start"]["line"] + 1,
                            "end": node["range"]["end"]["line"] + 1})
    return item


def definition_snippets(text, path, query, store=None, maximum_bytes=1800):
    language, tool = LANGUAGES.get(Path(path).suffix), shutil.which("ast-grep")
    if not language or not tool:
        return [{**part, "selection_kind": "lexical", "complete_definition": False}
                for part in chunks(text, query, maximum_bytes)]
    version = subprocess.run([tool, "--version"], capture_output=True, text=True, check=True, timeout=5).stdout.strip()
    key = [path, digest(text.encode()), version]
    parsed = cache_get(store, "snippet-ast", key) if store else None
    if parsed is None:
        if store:
            with resource_lock(store, "index"):
                parsed = parse_ast(path, {"text": text, "sha256": key[1]}, tool, language)
            cache_put(store, "snippet-ast", key, parsed)
        else:
            parsed = parse_ast(path, {"text": text, "sha256": key[1]}, tool, language)
    lines, terms, result = text.splitlines(), set(tokens(query)), []
    for symbol in parsed["symbols"]:
        kind = symbol["kind"]
        if "function" not in kind and "method" not in kind and kind != "variable_declarator":
            continue
        body = "\n".join(lines[symbol["start"] - 1:symbol["end"]])
        if kind == "variable_declarator" and "=>" not in body and "function" not in body:
            continue
        parts = chunks(body, query, maximum_bytes)
        if not parts:
            continue
        best = parts[0]
        result.append({**best, "start": symbol["start"] + best["start"] - 1,
                       "end": symbol["start"] + best["end"] - 1,
                       "score": best["score"] + 10 * len(terms.intersection(tokens(symbol["name"]))),
                       "symbol": symbol["name"], "definition_start": symbol["start"], "definition_end": symbol["end"],
                       "selection_kind": "AST function", "complete_definition": len(parts) == 1})
    return sorted(result, key=lambda item: (-item["score"], item["start"])) if result else [
        {**part, "selection_kind": "lexical", "complete_definition": False} for part in chunks(text, query, maximum_bytes)]


def ast_map(store, selected):
    pool = sources(store.root, selected)
    tool = shutil.which("ast-grep")
    if not tool:
        raise ValueError("AST retrieval requires ast-grep; use lexical retrieval until installed")
    version = subprocess.run([tool, "--version"], capture_output=True, text=True, check=True, timeout=5).stdout.strip()
    result = {"engine": version, "files": [], "cache_hits": 0,
              "notice": "Syntactic references only; not a complete or resolved call graph."}
    with resource_lock(store, "index"):
        for path, source in pool.items():
            language = LANGUAGES.get(Path(path).suffix)
            if not language:
                continue
            key = [version, path, source["sha256"]]
            item = cache_get(store, "ast", key, ttl=30 * 86400)
            if item is None:
                item = parse_ast(path, source, tool, language)
                cache_put(store, "ast", key, item)
            else:
                result["cache_hits"] += 1
            result["files"].append(item)
    return result


def repo_map(store, selected, budget=3000):
    if not 500 <= budget <= 5000:
        raise ValueError("Repo map budget must be 500–5000 estimated tokens")
    index = ast_map(store, selected)
    result = {"engine": index["engine"], "cache_hits": index["cache_hits"], "notice": index["notice"],
              "files": [], "indexed_files": len(index["files"]), "omitted_files": 0, "omitted_symbols": 0}
    for item in index["files"]:
        compact = {"path": item["path"], "sha256": item["sha256"], "test": item["test"],
                   "symbols": item["symbols"][:8], "reference_count": len(item["references"]),
                   "imports": item["imports"][:3]}
        result["files"].append(compact)
        result["omitted_symbols"] += max(0, len(item["symbols"]) - 8)
        if packing.estimate(encode(result)) > budget - 100:
            result["files"].pop()
            result["omitted_files"] += 1
    result["estimated_tokens"] = packing.estimate(encode(result)) + 30
    return result


def lookup(store, selected, symbol, mode="symbols", limit=8):
    if not symbol or len(symbol) > 200 or not 1 <= limit <= 30:
        raise ValueError("Provide a bounded symbol and result limit")
    index = ast_map(store, selected)
    result = []
    for file in index["files"]:
        if mode == "tests" and not file["test"]:
            continue
        group = "symbols" if mode == "symbols" else "references"
        for node in file[group]:
            # Qualified names remain visible; ambiguous references are not resolved heuristically.
            if symbol.casefold() not in node["name"].casefold():
                continue
            parents = [s for s in file["symbols"] if s["start"] <= node["start"] <= s["end"]]
            enclosing = min(parents, key=lambda s: s["end"] - s["start"]) if parents else None
            result.append({"path": file["path"], "sha256": file["sha256"], **node,
                           "enclosing": enclosing, "evidence": "AST syntax candidate"})
    result.sort(key=lambda r: (r["name"] != symbol, r["path"], r["start"]))
    return {"matches": result[:limit], "omitted": max(0, len(result) - limit),
            "cache_hits": index["cache_hits"], "notice": index["notice"]}


def lexical(store, selected, query, limit=8):
    if not query.strip() or len(query) > 1000 or not 1 <= limit <= 30:
        raise ValueError("Bound query to 1000 characters and results to 30")
    pool = sources(store.root, selected)
    key = [query, limit, [(p, s["sha256"]) for p, s in sorted(pool.items())]]
    cached = cache_get(store, "lexical", key)
    if cached is not None:
        return cached
    terms = set(tokens(query))
    counts = {path: Counter(tokens(path + " " + source["text"])) for path, source in pool.items()}
    lengths = {path: sum(counter.values()) for path, counter in counts.items()}
    average = max(1, sum(lengths.values()) / len(lengths))
    ranked = []
    for path, counter in counts.items():
        score = 0.0
        for term in terms:
            frequency = counter[term]
            containing = sum(term in other for other in counts.values())
            idf = math.log(1 + (len(counts) - containing + 0.5) / (containing + 0.5))
            score += idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * lengths[path] / average))
        if score <= 0:
            continue
        lines = pool[path]["text"].splitlines()
        hits = [i for i, line in enumerate(lines) if terms.intersection(tokens(line))]
        center = hits[0] if hits else 0
        start, end = max(1, center - 4), min(len(lines), center + 16)
        ranked.append({"path": path, "source": f"{path}:{start}:{end}", "sha256": pool[path]["sha256"],
                       "start": start, "end": end, "test": is_test(path), "score": round(score, 6)})
    result = sorted(ranked, key=lambda x: (-x["score"], x["path"]))[:limit]
    cache_put(store, "lexical", key, result)
    return result


def build_context(store, task_file, selected, required=(), budget=8000, symbol=None):
    if not 100 <= budget <= 12000:
        raise ValueError("Context build budget must be 100–12000 tokens")
    task = json.loads(read_source(store.root, task_file)["text"])
    matches = lexical(store, selected, task["goal"], limit=20)
    specs = []
    if symbol:
        for mode in ("symbols", "callers", "tests"):
            for match in lookup(store, selected, symbol, mode)["matches"]:
                node = match["enclosing"] if mode == "tests" and match["enclosing"] else match
                specs.append(f"{match['path']}:{node['start']}:{node['end']}")
    # Related tests are prioritized before optional implementation candidates.
    matches.sort(key=lambda x: (not x["test"], -x["score"]))
    specs.extend(m["source"] for m in matches)
    specs = list(dict.fromkeys(specs))[:30]
    result = packing.build(store.root, task, specs, list(required), [], budget)
    result["retrieval"] = {"selected": len(specs), "network_calls": 0,
                           "stop_reason": "local evidence packed; escalate only for a remaining evidence gap"}
    return result


def verify_context(root, document, budget=12000):
    if not isinstance(document, dict) or not isinstance(document.get("required_sources"), list):
        raise ValueError("Not a context packet")
    failures = []
    for source in document["required_sources"] + document.get("context", []):
        if "source" not in source or "sha256" not in source:
            failures.append("unverifiable source")
            continue
        try:
            fresh = read_source(root, source["source"])
            if fresh["sha256"] != source["sha256"] or fresh["text"] != source["text"]:
                failures.append(f"stale or modified: {source['source']}")
        except (OSError, ValueError):
            failures.append(f"unavailable: {source['source']}")
    count = packing.estimate(encode(document) + "\n")
    if count > budget:
        failures.append("context budget exceeded")
    return {"status": "failed" if failures else "passed", "failures": failures,
            "estimated_tokens": count, "fingerprint": digest(encode(document).encode())}
