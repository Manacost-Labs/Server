"""Compiler-backed TypeScript calls and honest syntactic fallback for other stacks."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import retrieval
from .common import encode, read_source
from .quality_common import resource_lock, sources


def lookup(store, selected, symbol, direction="callers", limit=10, config="tsconfig.json", definition_path=None):
    if direction not in {"callers", "callees"} or not symbol or len(symbol) > 200 or not 1 <= limit <= 30:
        raise ValueError("Select a bounded symbol, callers/callees and 1–30 results")
    pool = sources(store.root, selected)
    typed = [p for p in pool if Path(p).suffix in {".ts", ".tsx", ".js", ".jsx"}]
    if not typed:
        result = retrieval.lookup(store, selected, symbol, "callers", limit)
        if direction == "callees":
            index = retrieval.ast_map(store, selected)
            result["matches"] = [{"path": f["path"], "sha256": f["sha256"], **ref,
                                  "evidence": "AST syntax candidate; not resolved"}
                                 for f in index["files"] for node in f["symbols"] if node["name"] == symbol
                                 for ref in f["references"] if node["start"] <= ref["start"] <= node["end"]][:limit]
        return result
    if (store.root / config).exists():
        read_source(store.root, config)
    elif Path(config).is_absolute() or ".." in Path(config).parts:
        raise ValueError("Compiler config must be project-relative")
    node = shutil.which("node")
    if not node:
        raise ValueError("Compiler relationships require Node and locked quality dependencies")
    script = Path(__file__).resolve().parents[1] / "quality/typescript-relations.mjs"
    with resource_lock(store, "index"), tempfile.TemporaryFile() as stream:
        result = subprocess.run([node, "--max-old-space-size=256", str(script)],
                                input=encode({"root": str(store.root), "files": typed, "config": config}),
                                text=True, stdout=stream, stderr=subprocess.PIPE, timeout=45, check=False)
        if result.returncode:
            raise ValueError("TypeScript relationships failed; inspect dependencies/config or narrow source")
        stream.seek(0)
        raw = stream.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Compiler relationship output exceeds budget")
    graph = json.loads(raw)
    key = "target" if direction == "callers" else "caller"
    matches = [r for r in graph["relations"] if r.get(key) and r[key]["name"] == symbol
               and (not definition_path or r[key]["path"] == definition_path)]
    return {"engine": graph["engine"], "matches": matches[:limit], "omitted": max(0, len(matches) - limit),
            "imports": graph["imports"][:30], "unresolved": sum(r["target"] is None for r in graph["relations"]),
            "notice": graph["notice"], "unsupported_selected_files": [p for p in pool if p not in typed]}
