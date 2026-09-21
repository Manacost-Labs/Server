"""Offline source estimates, never observed Codex usage."""
import argparse
import json
import math
import os
import sys
from pathlib import Path

TOKENIZERS = {"gpt-4o": "o200k_base", "gpt-4": "cl100k_base", "gpt-3.5-turbo": "cl100k_base"}
EXCLUDED = {".git", "node_modules", "third_party", "vendor", ".venv", "__pycache__"}


def estimate_text(text, model="unknown", margin=0.15):
    if not math.isfinite(margin) or not 0.15 <= margin <= 2:
        raise ValueError("Budget margin must be between 0.15 and 2")
    count = None
    encoding = TOKENIZERS.get(model)
    if encoding:
        try:
            import tiktoken
            count = len(tiktoken.get_encoding(encoding).encode(text, disallowed_special=()))
        except (ImportError, OSError, ValueError):
            pass
    byte_count = len(text.encode("utf-8"))
    return {"model": model, "method": "compatible-tokenizer" if count is not None else "utf8-bytes-upper-estimate",
            "tokenizer": encoding if count is not None else None, "tokenizer_tokens": count,
            "utf8_bytes": byte_count, "margin": margin,
            "estimated_tokens": math.ceil((count if count is not None else byte_count) * (1 + margin)),
            "actual_codex_tokens": None,
            "notice": "Source estimate with margin; excludes hidden prompt/history/tool framing. "
                      "Unknown model tokenization is not guaranteed. Not subscription usage."}


def read_inputs(paths):
    selected = []
    for name in paths:
        path = Path(name)
        if path.is_symlink():
            raise ValueError("Select real files, not symlinks")
        if path.is_dir():
            for folder, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not Path(folder, d).is_symlink())
                selected.extend(Path(folder, f) for f in sorted(files) if not Path(folder, f).is_symlink())
                if len(selected) > 1000:
                    raise ValueError("More than 1000 files; narrow the selected paths")
        else:
            selected.append(path)
    chunks, size = [], 0
    for path in dict.fromkeys(selected):
        if not path.is_file():
            raise ValueError(f"Not a regular file: {path}")
        size += path.stat().st_size
        if size > 8 * 1024 * 1024:
            raise ValueError("More than 8 MiB; narrow the selected paths")
        chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=12000)
    parser.add_argument("--model", default="unknown")
    parser.add_argument("--margin", type=float, default=0.15)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    try:
        if args.limit < 1:
            raise ValueError("limit must be positive")
        result = estimate_text(read_inputs(args.paths), args.model, args.margin)
        result.update(limit=args.limit, exceeded=result["estimated_tokens"] > args.limit)
        print(json.dumps(result))
        return 3 if result["exceeded"] else 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"context-budget: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
