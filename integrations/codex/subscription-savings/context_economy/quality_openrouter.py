"""Native embedding/cross-encoder APIs using the existing private OpenRouter key."""

import json
import math
import re
import urllib.error
import urllib.request

from . import remote
from .common import digest, encode
from .typesafe import NoRedirect

ENDPOINTS = {"semantic-search": "https://openrouter.ai/api/v1/embeddings",
             "rerank": "https://openrouter.ai/api/v1/rerank"}
MODELS = {"semantic-search": "qwen/qwen3-embedding-8b", "rerank": "qwen/qwen3-reranker-8b"}
MAX_INPUT = 24000
MAX_RESPONSE = 2_000_000


def defaults(operation):
    return {"backend": "openrouter", "model": MODELS[operation], "revision": "openrouter-qwen3-8b-v1",
            "dimensions": 1024, "network": True, "max_cost_usd": 0.01, "daily_budget_usd": 0.10,
            "calls_per_day": 30, "max_prompt_price_per_million": 0.10}


def validate_input(payload):
    candidates = payload.get("candidates")
    if payload.get("operation") not in ENDPOINTS or not isinstance(candidates, list) or len(candidates) > 30:
        raise ValueError("OpenRouter retrieval requires a known operation and at most 30 chunks")
    if not isinstance(payload.get("query"), str) or not payload["query"].strip() or len(payload["query"]) > 1000:
        raise ValueError("OpenRouter query must be a nonempty string up to 1000 characters")
    texts = [payload["query"]]
    identifiers = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str) or not isinstance(candidate.get("text"), str):
            raise ValueError("OpenRouter candidates need string IDs and exact text")
        identifiers.append(candidate["id"])
        texts.append(candidate["text"])
    if len(set(identifiers)) != len(identifiers) or len(encode(payload).encode()) > MAX_INPUT:
        raise ValueError("Duplicate candidate IDs or remote input exceeds 24 KB; narrow sources")
    secret = re.compile(r"-----BEGIN .*PRIVATE KEY|\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_\-]{16,}"
                        r"|(?:api[_-]?key|password|secret|token)\s*[=:]\s*['\"][^'\"\s]{12,}['\"]", re.I)
    if any(secret.search(text) for text in texts):
        raise ValueError("Potential credential in retrieval input; remove it before remote use")


def send(operation, body, key):
    request = urllib.request.Request(ENDPOINTS[operation], data=encode(body).encode(), headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
    try:
        with opener.open(request, timeout=25) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError("OpenRouter response exceeds 2 MB")
        parsed = json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"OpenRouter {operation} HTTP {exc.code}; no automatic fallback or retry") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise ValueError("OpenRouter transport/response failed; reservation retained") from None
    if not isinstance(parsed, dict) or "error" in parsed:
        raise ValueError("OpenRouter returned an invalid/error response")
    return parsed


def convert(payload, response, provider):
    from .quality_providers import cosine

    semantic = payload["operation"] == "semantic-search"
    rows = response.get("data" if semantic else "results")
    expected = len(payload["candidates"]) + int(semantic)
    if not isinstance(rows, list) or any(not isinstance(item, dict) or type(item.get("index")) is not int for item in rows):
        raise ValueError("OpenRouter returned invalid result indices")
    if len(rows) != expected or {item["index"] for item in rows} != set(range(expected)):
        raise ValueError("OpenRouter omitted, duplicated or invented result indices")
    indexed = {item["index"]: item for item in rows}
    result = {"candidates": [], "usage": response.get("usage"), "provider": "openrouter",
              "model": provider["model"], "reported_model": response.get("model")}
    if semantic:
        for row in rows:
            vector = row.get("embedding")
            if not isinstance(vector, list) or len(vector) != provider.get("dimensions", 1024):
                raise ValueError("OpenRouter embedding dimensions differ from the configured vector space")
            cosine(vector, vector)
        result["query_embedding"] = indexed[0]["embedding"]
    for index, candidate in enumerate(payload["candidates"]):
        if semantic:
            value = {"embedding": indexed[index + 1]["embedding"]}
        else:
            score = indexed[index].get("relevance_score")
            if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError("OpenRouter rerank scores must be finite fractions")
            value = {"score": score}
        result["candidates"].append({"id": candidate["id"], **value})
    return result


def request(payload, provider, ledger=None):
    validate_input(payload)
    model, price = provider.get("model"), provider.get("max_prompt_price_per_million", 0.10)
    if not isinstance(model, str) or not re.fullmatch(r"[\w.-]+/[\w.:-]+", model):
        raise ValueError("Configure an explicit OpenRouter model ID")
    if type(price) not in (float, int) or not math.isfinite(price) or not 0 < price <= 0.10:
        raise ValueError("Retrieval routing price must be positive and at most $0.10/M input tokens")
    body = {"model": model, "provider": {"allow_fallbacks": False, "max_price": {"prompt": price}}}
    operation = payload["operation"]
    if operation == "semantic-search":
        dimensions = provider.get("dimensions", 1024)
        if type(dimensions) is not int or not 1 <= dimensions <= 4096:
            raise ValueError("Configure embedding dimensions in [1,4096]")
        query = "Instruct: Retrieve code snippets that implement the query.\nQuery: " + payload["query"]
        body.update(input=[query] + [item["text"] for item in payload["candidates"]],
                    dimensions=dimensions, encoding_format="float")
    else:
        if not payload["candidates"]:
            raise ValueError("Reranking requires at least one candidate")
        body.update(query=payload["query"], documents=[item["text"] for item in payload["candidates"]],
                    top_n=len(payload["candidates"]))
    # Same credential reader and budget ledger as the existing server assistants.
    key = remote.api_key()
    own_ledger = ledger is None
    ledger = remote.Ledger() if own_ledger else ledger
    try:
        reservation = ledger.reserve("quality:" + operation, digest(encode(body).encode()),
                                     provider.get("daily_budget_usd", 0.10),
                                     amount=provider.get("max_cost_usd", 0.01),
                                     call_limit=provider.get("calls_per_day", 30))
        response = send(operation, body, key)
        ledger.finish(reservation, response)
        return convert(payload, response, provider)
    finally:
        if own_ledger:
            ledger.close()
