"""Real-code provenance and native OpenRouter protocol regressions (offline)."""
import base64
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

INTEGRATION = Path(__file__).resolve().parents[1] / "integrations/codex/subscription-savings"
sys.path.insert(0, str(INTEGRATION))
from context_economy import (  # noqa: E402
    quality_openrouter,
    quality_providers,
    remote,
    retrieval,
)
from context_economy.common import Store  # noqa: E402


class RetrievalProviderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        (self.root / "src").mkdir()
        self.store = Store(self.root, Path(self.temporary.name) / "state")
        self.ledger = remote.Ledger(Path(self.temporary.name) / "ledger")

    def tearDown(self):
        self.ledger.close()
        self.store.close()
        self.temporary.cleanup()

    def args(self, **extra):
        defaults = dict(command="semantic-search", query="rate limit", source=["src"], limit=2,
                        config=".ai/manacost-quality.json", evidence_gap="local names are ambiguous",
                        allow_remote=False, preview_remote=False, library=None, library_version=None,
                        rerank_references=False)
        return SimpleNamespace(**{**defaults, **extra})

    def payload(self, operation="semantic-search"):
        return {"operation": operation, "query": "rate limit", "revision": "test-v1", "max_results": 2,
                "candidates": [{"id": "a", "text": "reject requests over limit"}, {"id": "b", "text": "save a file"}]}

    def provider(self, operation="semantic-search"):
        return {**quality_openrouter.defaults(operation), "dimensions": 2}

    def test_embedding_response_uses_indices_not_provider_order(self):
        response = {"data": [{"index": 2, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]},
                             {"index": 1, "embedding": [1, 0]}], "usage": {"cost": 0.00001}}
        with mock.patch.object(quality_openrouter, "send", return_value=response) as send, \
                mock.patch.object(remote, "api_key", return_value="synthetic-key"):
            result = quality_openrouter.request(self.payload(), self.provider(), self.ledger)
        self.assertEqual([1, 0], result["query_embedding"])
        self.assertEqual([0, 1], result["candidates"][1]["embedding"])
        self.assertEqual(3, len(send.call_args.args[1]["input"]))
        self.assertEqual("qwen/qwen3-embedding-8b", send.call_args.args[1]["model"])
        self.assertAlmostEqual(0.00001, self.ledger.summary()["reported_cost_usd"])

    def test_duplicate_missing_and_nonfinite_embeddings_fail(self):
        for data in ([{"index": 0, "embedding": [1, 0]}] * 3,
                     [{"index": i, "embedding": [float("nan"), 0]} for i in range(3)],
                     [{"index": i, "embedding": [1]} for i in range(3)]):
            with self.subTest(data=data), self.assertRaises(ValueError):
                quality_openrouter.convert(self.payload(), {"data": data}, self.provider())

    def test_native_reranker_maps_all_scores_without_inventing_source_ids(self):
        response = {"results": [{"index": 1, "relevance_score": 0.1}, {"index": 0, "relevance_score": 0.9}]}
        result = quality_openrouter.convert(self.payload("rerank"), response, self.provider("rerank"))
        ranked = quality_providers.rank_response(self.payload("rerank"), result, "rerank")
        self.assertEqual("a", ranked["matches"][0]["id"])
        response["results"][0]["index"] = 10
        with self.assertRaises(ValueError):
            quality_openrouter.convert(self.payload("rerank"), response, self.provider("rerank"))

    def test_native_api_failure_retains_shared_budget_reservation(self):
        with mock.patch.object(quality_openrouter, "send", side_effect=ValueError("HTTP 503")), \
                mock.patch.object(remote, "api_key", return_value="synthetic-key"), self.assertRaises(ValueError):
            quality_openrouter.request(self.payload(), self.provider(), self.ledger)
        self.assertGreater(self.ledger.summary()["unknown_reserved_usd"], 0)

    def test_preview_and_cache_miss_never_load_credentials(self):
        (self.root / "src/limiter.py").write_text("def rate_limit():\n    return False\n")
        with mock.patch.object(remote, "api_key", side_effect=AssertionError("credential access")):
            result = quality_providers.run(self.store, self.args(preview_remote=True))
            self.assertFalse(result["sent"])
            self.assertIn("qwen/qwen3-embedding-8b", json.dumps(result))
            with self.assertRaises(ValueError):
                quality_providers.run(self.store, self.args())

    def test_cached_usage_is_not_reported_as_a_new_charge(self):
        (self.root / "src/limiter.py").write_text("def rate_limit():\n    return False\n")
        def response(payload, provider):
            return {"query_embedding": [1, 0], "candidates": [{"id": item["id"], "embedding": [1, 0]}
                    for item in payload["candidates"]], "usage": {"cost": 0.001}, "model": provider["model"]}
        with mock.patch.object(quality_openrouter, "request", side_effect=response) as request:
            fresh = quality_providers.run(self.store, self.args(allow_remote=True))
            cached = quality_providers.run(self.store, self.args())
        self.assertEqual(1, request.call_count)
        self.assertEqual(1, fresh["openrouter_calls"])
        self.assertEqual(0, cached["openrouter_calls"])
        self.assertIsNone(cached["usage"])
        self.assertEqual(0.001, cached["cached_usage"]["cost"])
        self.assertEqual(0, cached["call_cost_usd"])

    def test_shortlist_includes_real_implementation_beyond_line_sixty(self):
        text = "# unrelated initialization\n" * 120 + "def rate_limit(key):\n    return redis.incr(key) < 10\n"
        (self.root / "src/limiter.py").write_text(text)
        result = quality_providers.run(self.store, self.args(preview_remote=True))
        candidates = result["preview"]["candidates"]
        best = candidates[0]
        self.assertIn("def rate_limit", best["text"])
        self.assertGreater(int(best["source"].split(":")[-2]), 60)
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), best["sha256"])

    def test_function_name_beats_repeated_constructor_documentation(self):
        source = ('class Lock:\n    def __init__(self):\n        """' + 'acquire ' * 100 + '"""\n        pass\n'
                  '    def acquire(self):\n        return self.redis.set("lock", "value", nx=True)\n')
        selected = retrieval.definition_snippets(source, "lock.py", "acquire", self.store)
        self.assertEqual("acquire", selected[0]["symbol"])
        self.assertIn("def acquire", selected[0]["text"])
        self.assertTrue(selected[0]["complete_definition"])

    def test_reference_search_excludes_test_sources_by_default(self):
        capture, _ = self.github()
        def search(argv, *args, **kwargs):
            result = capture(argv, *args, **kwargs)
            if "search/code" in argv:
                result["items"][0]["path"] = "tests/test_lock.py"
            return result
        with mock.patch.object(quality_providers, "capture", side_effect=search):
            result = quality_providers.references(self.args(command="reference-search"))
        self.assertEqual([], result["references"])
        self.assertIn("test source excluded", result["rejected"][0]["reason"])

    def test_shared_budget_cannot_be_reset_by_switching_retrieval_operation(self):
        self.ledger.reserve("quality:semantic-search", "a", 0.02, amount=0.01, call_limit=1)
        with self.assertRaises(ValueError):
            self.ledger.reserve("quality:rerank", "b", 0.02, amount=0.01, call_limit=1)

    def test_secrets_are_rejected_before_any_openrouter_request(self):
        payload = self.payload()
        payload["candidates"][0]["text"] = 'api_key = "' + 'sk-or-' + 'a' * 40 + '"'
        with mock.patch.object(quality_openrouter, "send") as send, self.assertRaises(ValueError):
            quality_openrouter.request(payload, self.provider(), self.ledger)
        send.assert_not_called()

    def github(self, corrupt=False):
        code = "# project header\n" * 80 + "def rate_limit(key):\n    return redis.incr(key) < 10\n"
        raw = code.encode()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        def capture(argv, *args, **kwargs):
            if "search/code" in argv:
                return {"items": [{"repository": {"full_name": "example/limiter"}, "path": "limiter.py", "sha": blob}]}
            route = argv[2]
            if route.endswith("/commits/main"):
                return {"sha": "a" * 40}
            if "/contents/" in route:
                return {"type": "file", "encoding": "base64", "size": len(raw),
                        "sha": "b" * 40 if corrupt else blob, "content": base64.b64encode(raw).decode()}
            return {"default_branch": "main", "license": {"spdx_id": "MIT"}, "archived": False}
        return capture, code

    def test_reference_is_exact_pinned_github_code_with_verified_blob(self):
        capture, code = self.github()
        with mock.patch.object(quality_providers, "capture", side_effect=capture):
            result = quality_providers.references(self.args(command="reference-search", query="rate_limit repo:example/limiter"))
        reference = result["references"][0]
        self.assertTrue(reference["blob_verified"])
        self.assertIn("/blob/" + "a" * 40 + "/limiter.py#L", reference["url"])
        self.assertEqual("\n".join(code.splitlines()[reference["start"] - 1:reference["end"]]), reference["text"])
        self.assertIn("def rate_limit", reference["text"])
        self.assertFalse(reference["tests_verified"])

    def test_corrupt_github_body_cannot_be_returned_as_existing_code(self):
        capture, _ = self.github(corrupt=True)
        with mock.patch.object(quality_providers, "capture", side_effect=capture):
            result = quality_providers.references(self.args(command="reference-search"))
        self.assertEqual([], result["references"])
        self.assertTrue(result["rejected"])
