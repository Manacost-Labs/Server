"""Probe-assisted context from explicitly bounded local source and test directories."""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from . import packing
from .common import read_source

EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".php", ".java", ".c", ".cpp", ".h"}
EXCLUDED = {"node_modules", "vendor", "dist", "build", "coverage", "__pycache__", "venv", "releases", "backups"}


def candidates(root, paths):
    if not 1 <= len(paths) <= 8:
        raise ValueError("Select 1–8 narrow search paths")
    selected = {}
    total = 0
    visited = 0
    for name in paths:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("Search paths must be explicit project-relative source directories or files")
        path = root / relative
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p.is_relative_to(root)):
            raise ValueError("Symlink search paths are not allowed")
        if not path.exists() or not path.resolve().is_relative_to(root):
            raise ValueError("Search path is missing or outside the project")
        files = [path] if path.is_file() else []
        if path.is_dir():
            for directory, dirs, names in os.walk(path, followlinks=False):
                visited += 1
                if visited > 200:
                    raise ValueError("Search exceeds 200 directories; select narrower paths")
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in EXCLUDED
                                 and not (Path(directory) / d).is_symlink())
                files.extend(Path(directory) / n for n in sorted(names)
                             if Path(n).suffix in EXTENSIONS and not n.startswith("."))
                if len(files) > 100:
                    raise ValueError("Search exceeds 100 code files; select narrower directories")
        for file in files:
            if file.suffix not in EXTENSIONS or file.is_symlink():
                continue
            spec = file.relative_to(root).as_posix()
            if spec in selected:
                continue
            source = read_source(root, spec)
            selected[spec] = source
            total += len(source["text"].encode())
            if len(selected) > 100 or total > 2 * 1024 * 1024:
                raise ValueError("Search exceeds 100 files or 2 MiB; narrow the selected paths")
    return selected


def run(store, args):
    if not 1 <= len(args.source) <= 6 or not 100 <= args.budget <= 12000:
        raise ValueError("Select 1–6 changed fragments and budget in [100,12000]")
    task_source = read_source(store.root, args.task)
    task = json.loads(task_source["text"])
    changed = [read_source(store.root, s) for s in args.source]
    # Changed code is mandatory. Test/dependency matches are optional and budgeted.
    mandatory = [*args.source, *args.required]
    baseline = packing.build(store.root, task, [], mandatory, [], args.budget)
    covered = []
    for source in json.loads(baseline["text"])["required_sources"]:
        match = re.fullmatch(r"(.+?):(\d+):(\d+)", source["source"])
        covered.append((source["path"], int(match[2]) if match else 1,
                        int(match[3]) if match else len(source["text"].splitlines())))
    pool = candidates(store.root, args.search_in)
    query = args.query
    if query is None:
        symbols = sorted(set(re.findall(r"\b([A-Za-z_][A-Za-z_0-9]{2,})\s*\(",
                                        "\n".join(s["text"] for s in changed))) -
                         {"print", "range", "len", "str", "int", "dict", "list", "set", "super"})
        query = " OR ".join(symbols[:12])
    if not isinstance(query, str) or not query.strip() or len(query) > 512:
        raise ValueError("No bounded symbol query; provide --query explicitly")
    specs = []
    status = "probe"
    try:
        with tempfile.TemporaryDirectory(prefix="context-probe-") as directory:
            staging = Path(directory)
            for spec, source in pool.items():
                target = staging / spec
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source["text"])
            # Probe sees only the allowed snapshots, never a server-wide directory.
            with tempfile.TemporaryFile() as output:
                process = subprocess.run(["probe", "search", query, str(staging), "--format", "json",
                                          "--allow-tests", "--max-results", "8", "--max-tokens", "1500",
                                          "--max-bytes", "6000"], stdout=output, stderr=subprocess.DEVNULL,
                                         timeout=20, check=True)
                output.seek(0)
                raw = output.read(128001)
                if len(raw) > 128000 or process.returncode:
                    raise ValueError("Invalid Probe output")
                found = json.loads(raw)
            if not isinstance(found, dict) or not isinstance(found.get("results"), list) or len(found["results"]) > 8:
                raise ValueError("Invalid Probe result set")
            for match in found.get("results", []):
                file = Path(match["file"])
                if not file.is_absolute():
                    file = staging / file
                spec = file.relative_to(staging).as_posix()
                if spec not in pool:
                    raise ValueError("Probe returned a file outside the selected snapshots")
                start, end = match["lines"]
                if type(start) is not int or type(end) is not int:
                    raise ValueError("Invalid Probe line range")
                fragment = f"{spec}:{start}:{end}"
                source = read_source(store.root, fragment)
                if source["sha256"] != pool[spec]["sha256"]:
                    raise ValueError("Source changed during Probe search")
                if any(spec == name and start <= right and end >= left for name, left, right in covered):
                    continue  # Avoid re-sending the changed function inside a larger search match.
                if fragment not in mandatory:
                    specs.append(fragment)
                    covered.append((spec, start, end))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        status = "fallback"
        specs = []
    packet = packing.build(store.root, task, specs, mandatory, [], args.budget) if specs else baseline
    checked = [*changed, *pool.values(), *json.loads(packet["text"])["required_sources"], task_source]
    if any(read_source(store.root, s["source"])["sha256"] != s["sha256"] for s in checked):
        raise ValueError("Selected context changed; repeat the focused search")
    return {"status": status, "packet": json.loads(packet["text"]), "candidate_sources": specs,
            "estimated_tokens": packet["estimated_tokens"],
            "notice": "Probe matches are candidate dependencies/tests, not a complete call graph. "
                      "Changed fragments and ancestor instructions are pinned; investigate missing evidence explicitly."}
