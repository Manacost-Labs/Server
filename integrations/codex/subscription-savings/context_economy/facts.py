"""Preserve explicitly selected exact facts; no claim of semantic completeness."""

import json

from .common import read_source


def load(root, spec, candidates, original):
    if not spec:
        return [], None
    source = read_source(root, spec)
    facts = json.loads(source["text"])
    if not isinstance(facts, list) or not 1 <= len(facts) <= 20:
        raise ValueError("Critical facts must be a list of 1–20 {source,quote} objects")
    lookup = {s["source"]: s for s in candidates.values()}
    baseline_sources = {s.get("source") for s in original["context"] + original["required_sources"]}
    for fact in facts:
        if not isinstance(fact, dict) or set(fact) != {"source", "quote"}:
            raise ValueError("A critical fact needs exactly source and quote")
        if not isinstance(fact["source"], str) or fact["source"] not in lookup:
            raise ValueError("Critical fact must reference an explicit optional source fragment")
        quote = fact["quote"]
        if not isinstance(quote, str) or not quote.strip() or len(quote) > 2000 or quote not in lookup[fact["source"]]["text"]:
            raise ValueError("Critical fact quote is not present in the selected fragment")
        if fact["source"] not in baseline_sources:
            raise ValueError("Critical source missing from fallback packet; raise budget or narrow sources")
    return facts, source


def restore(packet, facts, candidates):
    lookup = {s["source"]: s for s in candidates.values()}
    restored = set()
    for fact in facts:
        source = fact["source"]
        present = any(item.get("source") == source and fact["quote"] in item.get("quote", item.get("text", ""))
                      for item in packet["context"])
        if not present:
            packet["context"] = [item for item in packet["context"] if item.get("source") != source]
            packet["context"].append(dict(lookup[source], restoration="Required exact fact omitted by draft"))
            restored.add(source)
    return sorted(restored)
