#!/usr/bin/env python3
"""Provision public tokenizer data during release preparation, never at runtime."""
import argparse
import base64
import hashlib
import json
from pathlib import Path


def provision(output):
    import tiktoken

    root = Path(output)
    if root.exists():
        raise ValueError("Tokenizer destination must be new")
    encoding = tiktoken.get_encoding("o200k_base")
    raw = b"".join(base64.b64encode(token) + b" " + str(rank).encode() + b"\n"
                   for token, rank in sorted(encoding._mergeable_ranks.items(), key=lambda item: item[1]))
    metadata = {"encoding": "o200k_base", "ranks_sha256": hashlib.sha256(raw).hexdigest(),
                "pat_str": encoding._pat_str, "special_tokens": encoding._special_tokens,
                "source": "https://github.com/openai/tiktoken", "tiktoken_version": tiktoken.__version__}
    root.mkdir(parents=True, mode=0o700)
    (root / "o200k_base.tiktoken").write_bytes(raw)
    (root / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    provision(parser.parse_args().output)
