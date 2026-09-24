"""Retrieval evaluation reports grounded ranks without inventing model savings."""

import sys
import tempfile
import unittest
from pathlib import Path

INTEGRATION = Path(__file__).resolve().parents[1] / "integrations/codex/subscription-savings"
sys.path.insert(0, str(INTEGRATION))
from context_economy.common import Store  # noqa: E402
from context_economy import retrieval, retrieval_eval  # noqa: E402


class RetrievalEvaluationTests(unittest.TestCase):
    def test_empty_ast_reference_has_no_symbol_name(self):
        self.assertEqual("", retrieval._name("()", "references"))
        self.assertEqual("", retrieval._name("  ", "references"))

    def test_local_suite_measures_rank_and_uses_no_remote_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src").mkdir()
            (root / "src/target.py").write_text("def public_profile_path(value):\n    return '/id/' + value\n")
            (root / "src/other.py").write_text("def unrelated():\n    return 1\n")
            store = Store(root, root / "state")
            try:
                cases = [{"id": "profile", "query": "public profile path", "source":
                          ["src/target.py", "src/other.py"], "expected_path": "src/target.py"}]
                result = retrieval_eval.evaluate(store, cases)
                self.assertEqual(1, result["cases"][0]["rank"])
                self.assertEqual(1.0, result["hit_at_k"])
                self.assertEqual(1.0, result["mrr_at_k"])
                self.assertEqual(0, result["openrouter_calls"])
            finally:
                store.close()

    def test_rejects_unbounded_or_unverifiable_cases(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = Store(root, root / "state")
            try:
                with self.assertRaises(ValueError):
                    retrieval_eval.evaluate(store, [{"id": str(i)} for i in range(21)])
                with self.assertRaises(ValueError):
                    retrieval_eval.evaluate(store, [{"id": "bad", "query": "foo", "source": ["x.py"],
                                                     "expected_path": "../secret.py"}])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
