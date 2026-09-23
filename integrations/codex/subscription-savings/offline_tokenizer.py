"""Offline o200k context estimate; this never selects or calls an inference model."""
import base64
import hashlib
import json
import math
import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=2)
def load(directory):
    """Construct directly from provisioned ranks; no tiktoken network loader."""
    import tiktoken

    root = Path(directory)
    metadata_path, ranks_path = root / "metadata.json", root / "o200k_base.tiktoken"
    if metadata_path.stat().st_size > 8000 or ranks_path.stat().st_size > 5_000_000:
        raise ValueError("Tokenizer artifacts exceed bounds")
    metadata = json.loads(metadata_path.read_text())
    raw = ranks_path.read_bytes()
    if metadata["encoding"] != "o200k_base" or hashlib.sha256(raw).hexdigest() != metadata["ranks_sha256"]:
        raise ValueError("Tokenizer provenance mismatch")
    ranks = {base64.b64decode(token, validate=True): int(rank) for token, rank in (line.split() for line in raw.splitlines())}
    if len(ranks) != 199998 or set(ranks.values()) != set(range(199998)):
        raise ValueError("Unexpected o200k vocabulary")
    return tiktoken.Encoding(name="quality-o200k-base", pat_str=metadata["pat_str"],
                             mergeable_ranks=ranks, special_tokens=metadata["special_tokens"])


def estimate(text):
    directory = os.environ.get("MANACOST_TOKENIZER_CACHE", str(Path(__file__).resolve().parent / "quality/tokenizer-cache"))
    try:
        encoding = load(directory)
    except (ImportError, OSError, ValueError, KeyError, TypeError):
        return None
    count = len(encoding.encode(text, disallowed_special=()))
    return {"estimated_tokens": math.ceil(count * 1.15), "tokenizer_tokens": count,
            "estimator": "Offline o200k_base + 15%; proxy estimate, not observed usage or a guarantee for every model"}
