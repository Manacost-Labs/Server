"""Regressions for local-first flow, immutable source and incremental updates."""
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations/codex/subscription-savings"))
from context_economy import quality_openrouter, relations, retrieval_flow
from context_economy.common import Store, read_source


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src/lock.py").write_text("def acquire(token):\n    return token\n")
        self.store = Store(self.root, self.root / "state")
        self.addCleanup(self.store.close)

    def args(self, **kwargs):
        return Namespace(**{"query": "acquire token", "source": ["src"], "symbol": None, "limit": 3,
                            "config": ".ai/manacost-quality.json", "semantic_fallback": False,
                            "allow_remote": False, "preview_remote": False, "evidence_gap": "", **kwargs})

    def test_exact_symbol_avoids_remote_even_with_fallback(self):
        with mock.patch.object(quality_openrouter, "request") as remote:
            result = retrieval_flow.retrieve(self.store, self.args(symbol="acquire", semantic_fallback=True))
        remote.assert_not_called()
        self.assertEqual(result["openrouter_calls"], 0)
        self.assertEqual(result["matches"][0]["symbol"], "acquire")

    def test_incremental_rename_delete_and_source_staleness(self):
        first = retrieval_flow.update_index(self.store, ["src"])
        self.assertEqual(first["changed"], ["src/lock.py"])
        old = read_source(self.root, "src/lock.py")["sha256"]
        self.assertIn("return token", retrieval_flow.definition(self.store, "src/lock.py:1:2", old)["text"])
        again = retrieval_flow.update_index(self.store, ["src"])
        self.assertEqual(again["changed"], [])
        self.assertEqual(again["cache_hits"], 1)
        (self.root / "src/lock.py").rename(self.root / "src/new.py")
        moved = retrieval_flow.update_index(self.store, ["src"])
        self.assertEqual(moved["removed"], ["src/lock.py"])
        self.assertEqual(moved["changed"], ["src/new.py"])
        (self.root / "src/new.py").write_text("def acquire():\n    return False\n")
        with self.assertRaisesRegex(ValueError, "changed"):
            retrieval_flow.definition(self.store, "src/new.py", old)
        (self.root / "src/new.py").unlink()
        empty = retrieval_flow.update_index(self.store, ["src"])
        self.assertEqual(empty["removed"], ["src/new.py"])
        self.assertEqual(empty["indexed_files"], 0)
        (self.root / "src").rmdir()
        self.assertEqual(retrieval_flow.update_index(self.store, ["src"])["indexed_files"], 0)
        with self.assertRaisesRegex(ValueError, "never indexed"):
            retrieval_flow.update_index(self.store, ["never-existed"])

    def test_two_real_protocol_stages_then_no_calls_for_cached_repeat(self):
        def response(payload, provider):
            if payload["operation"] == "semantic-search":
                return {"query_embedding": [1, 0], "candidates": [
                    {"id": item["id"], "embedding": [1, 0]} for item in payload["candidates"]],
                    "model": provider["model"], "usage": {"cost": 0.001}}
            return {"candidates": [{"id": item["id"], "score": 0.9} for item in payload["candidates"]],
                    "model": provider["model"], "usage": {"cost": 0.001}}
        args = self.args(semantic_fallback=True, allow_remote=True, evidence_gap="Ambiguous local match")
        with mock.patch.object(quality_openrouter, "request", side_effect=response) as remote:
            first = retrieval_flow.retrieve(self.store, args)
            self.assertEqual(remote.call_count, 2)
            args.allow_remote = False
            second = retrieval_flow.retrieve(self.store, args)
            self.assertEqual(remote.call_count, 2)
        self.assertEqual(first["openrouter_calls"], 2)
        self.assertEqual(second["openrouter_calls"], 0)
        self.assertEqual(second["matches"][0]["text"], "def acquire(token):\n    return token")

    def test_compiler_resolves_alias_without_conflating_same_named_function(self):
        (self.root / "src/lock.ts").write_text("export function acquire() { return true; }\n")
        (self.root / "src/unrelated.ts").write_text("export function acquire() { return false; }\n")
        (self.root / "src/use.ts").write_text("import {acquire as take} from './lock';\nexport function execute() { return take(); }\n")
        result = relations.lookup(self.store, ["src"], "acquire", definition_path="src/lock.ts")
        self.assertEqual(len(result["matches"]), 1)
        edge = result["matches"][0]
        self.assertEqual(edge["call"]["name"], "take")
        self.assertEqual(edge["caller"]["name"], "execute")
        self.assertEqual(edge["target"]["path"], "src/lock.ts")
        self.assertFalse(edge["runtime_dispatch_verified"])
        unrelated = relations.lookup(self.store, ["src"], "acquire", definition_path="src/unrelated.ts")
        self.assertEqual(unrelated["matches"], [])
        callees = relations.lookup(self.store, ["src"], "execute", direction="callees")
        self.assertEqual(callees["matches"][0]["target"]["name"], "acquire")


if __name__ == "__main__":
    unittest.main()
