"""Retrieval evaluation reports grounded ranks without inventing model savings."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

INTEGRATION = Path(__file__).resolve().parents[1] / "integrations/codex/subscription-savings"
sys.path.insert(0, str(INTEGRATION))
from context_economy.common import Store  # noqa: E402
from context_economy import retrieval, retrieval_eval  # noqa: E402


class RetrievalEvaluationTests(unittest.TestCase):
    def test_lexical_scores_are_stable_across_python_hash_seeds(self):
        script = ("from context_economy.retrieval import chunks; "
                  "text='alpha '*1+'beta '*2+'gamma '*3+'delta '*4+'epsilon '*5; "
                  "print(repr(chunks(text,'alpha beta gamma delta epsilon')[0]['score']))")
        scores = [subprocess.check_output([sys.executable, "-c", script], text=True,
                                          env={**os.environ, "PYTHONPATH": str(INTEGRATION),
                                               "PYTHONHASHSEED": str(seed)}).strip()
                  for seed in (1, 2, 3, 4)]
        self.assertEqual(1, len(set(scores)))

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

    def test_versioned_project_manifest_and_negative_case(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src").mkdir()
            (root / "src/target.py").write_text("def profile_path(value):\n    return '/id/' + value\n")
            document = {"version": 1, "cases": [
                {"id": "positive", "query": "profile path", "source": ["src/target.py"],
                 "expected_path": "src/target.py"},
                {"id": "absent", "query": "refund subscription invoice", "source": ["src/target.py"],
                 "expected_path": None},
            ]}
            (root / "cases.json").write_text(json.dumps(document))
            store = Store(root, root / "state")
            try:
                cases, fingerprint = retrieval_eval.load_manifest(store, "cases.json")
                result = retrieval_eval.evaluate(store, cases)
                self.assertEqual(64, len(fingerprint))
                self.assertEqual(1, result["positive_cases"])
                self.assertEqual(1, result["negative_cases"])
                self.assertEqual(1.0, result["hit_at_k"])
                self.assertEqual(1.0, result["negative_rejection_rate"])
                self.assertTrue(result["cases"][1]["correct"])
                document["version"] = 2
                (root / "cases.json").write_text(json.dumps(document))
                with self.assertRaises(ValueError):
                    retrieval_eval.load_manifest(store, "cases.json")
            finally:
                store.close()

    def test_duplicate_case_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp), Path(temp) / "state")
            try:
                case = {"id": "same", "query": "find code", "source": ["src/a.py"],
                        "expected_path": "src/a.py"}
                with self.assertRaises(ValueError):
                    retrieval_eval.evaluate(store, [case, case])
            finally:
                store.close()

    def test_select_cases_rejects_unknown_ids_and_preserves_manifest_order(self):
        cases = [{"id": "one"}, {"id": "two"}, {"id": "three"}]
        self.assertEqual([cases[0], cases[2]], retrieval_eval.select_cases(cases, ["three", "one"]))
        with self.assertRaises(ValueError):
            retrieval_eval.select_cases(cases, ["missing"])


if __name__ == "__main__":
    unittest.main()
