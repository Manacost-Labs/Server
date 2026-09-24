import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

INTEGRATION = Path(__file__).resolve().parents[1] / "integrations/codex/subscription-savings"
sys.path.insert(0, str(INTEGRATION))

from context_economy import (  # noqa: E402
    assets,
    design,
    quality_checks,
    quality_policy,
    quality_providers,
    retrieval,
)
from context_economy.common import Store  # noqa: E402
from context_economy.quality_common import resource_lock, sources  # noqa: E402


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "project"
        self.root.mkdir()
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src/cache.py").write_text("# fake()\ndef cache(value):\n    return value\n")
        (self.root / "tests/test_cache.py").write_text("from cache import cache\ndef test_cache():\n    assert cache(1) == 1\n")
        self.store = Store(self.root, Path(self.tmp.name) / "state")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def check(self, code="pass", **kwargs):
        return {"id": "example", "argv": [sys.executable, "-c", code], **kwargs}

    def run_checks(self, checks, **kwargs):
        return quality_checks.verify(self.store, {"version": 1, "checks": checks}, ["src/cache.py"], **kwargs)

    def test_rejects_unbounded_and_symlink_sources(self):
        (self.root / "link").symlink_to(self.root / "src")
        for path in (".", "../", "link", "/tmp", "secrets"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                sources(self.root, [path])

    def test_svg_normalization_preserves_source_and_rejects_active_content(self):
        source = '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 24 24"><path fill="#123456" d="M0 0h24v24H0z"/></svg>'
        (self.root / "icon.svg").write_text(source)
        args = SimpleNamespace(source="icon.svg", output="icons/ready.svg", monochrome=True)
        self.assertEqual("passed", assets.normalize_svg(self.store, args)["status"])
        self.assertEqual(source, (self.root / "icon.svg").read_text())
        normalized = (self.root / "icons/ready.svg").read_text()
        self.assertIn("currentColor", normalized)
        self.assertNotIn('width="512"', normalized)
        with self.assertRaises(ValueError):
            assets.normalize_svg(self.store, args)
        (self.root / "icon.svg").write_text(source.replace('<path ', '<script>alert(1)</script><path '))
        args.output = "icons/unsafe.svg"
        with self.assertRaises(ValueError):
            assets.normalize_svg(self.store, args)
        self.assertFalse((self.root / args.output).exists())

    def test_embeddings_reuse_unchanged_chunks_across_queries(self):
        payload = {"operation": "semantic-search", "revision": "model-v1", "query": "one", "max_results": 1,
                   "candidates": [{"id": "src/a.py", "source": "src/a.py:1:1", "sha256": "first", "text": "a"}]}
        def backend(argv, request):
            return {"query_embedding": [1, 0], "candidates": [
                {"id": item["id"], "embedding": [1, 0]} for item in request["candidates"]]}
        with mock.patch.object(quality_providers, "capture", side_effect=backend) as capture:
            self.assertEqual(0, quality_providers.semantic_cached(self.store, ["backend"], payload)["embedding_cache_hits"])
            payload["query"] = "two"
            self.assertEqual(1, quality_providers.semantic_cached(self.store, ["backend"], payload)["embedding_cache_hits"])
            self.assertEqual([], capture.call_args.args[1]["candidates"])
            payload["candidates"][0]["sha256"] = "changed"
            self.assertEqual(0, quality_providers.semantic_cached(self.store, ["backend"], payload)["embedding_cache_hits"])

    def test_heavy_resource_enforcement_is_required_when_configured(self):
        config = {"version": 1, "checks": [self.check(tier="heavy")],
                  "heavy_limits": {"cpu_percent": 100, "memory_mb": 256}}
        with mock.patch.object(quality_checks.output, "run", return_value={
                "timed_out": False, "exit_code": 1, "log": "scope.log", "preview": "scope unavailable"}) as run:
            result = quality_checks.verify(self.store, config, ["src/cache.py"], risk="high", allow_heavy=True)
            self.assertEqual("failed", result["status"])
            self.assertIn("--property=MemoryMax=256M", run.call_args.args[1])
            self.assertIn("--property=CPUQuota=100%", run.call_args.args[1])

    @unittest.skipUnless(shutil.which("ast-grep"), "ast-grep unavailable")
    def test_ast_ignores_comments_finds_tests_and_invalidates_cache(self):
        selected = ["src", "tests"]
        self.assertEqual(2, len(retrieval.ast_map(self.store, selected)["files"]))
        self.assertEqual([], retrieval.lookup(self.store, selected, "fake", "callers")["matches"])
        match = retrieval.lookup(self.store, selected, "cache", "tests")["matches"][0]
        self.assertEqual("test_cache", match["enclosing"]["name"])
        self.assertEqual(2, retrieval.ast_map(self.store, selected)["cache_hits"])
        (self.root / "src/cache.py").write_text("def replaced():\n    return 2\n")
        self.assertEqual(1, retrieval.ast_map(self.store, selected)["cache_hits"])
        self.assertEqual([], retrieval.lookup(self.store, ["src"], "cache")["matches"])

    def test_public_repo_map_does_not_dump_the_complete_index(self):
        (self.root / "src/many.py").write_text("\n".join(f"def function_{n}():\n    return {n}" for n in range(100)))
        result = retrieval.repo_map(self.store, ["src/many.py"], budget=1600)
        self.assertLessEqual(result["estimated_tokens"], 1600)
        self.assertGreater(result["omitted_symbols"] + result["omitted_files"], 0)

    def test_packet_verification_detects_tampering(self):
        (self.root / "task.json").write_text(json.dumps({"goal": "cache behavior", "criteria": ["tests pass"], "constraints": []}))
        packet = retrieval.build_context(self.store, "task.json", ["src", "tests"], ["src/cache.py"], budget=2000)
        document = json.loads(packet["text"])
        self.assertEqual("passed", retrieval.verify_context(self.root, document, 2000)["status"])
        document["required_sources"][0]["text"] = "injected"
        self.assertEqual("failed", retrieval.verify_context(self.root, document, 2000)["status"])

    def test_router_is_small_and_raises_sensitive_risk(self):
        minimal = quality_policy.route(["src/name.py"], "mechanical")
        self.assertEqual(["token/base"], [m["id"] for m in minimal["modules"]])
        auth = quality_policy.route(["auth/login.go"])
        self.assertEqual("high", auth["risk"])
        self.assertLess(auth["estimated_tokens"], 1500)

    def test_router_raises_risk_for_secrets_crypto_and_wordpress_config(self):
        for path in ("config/secrets.py", "src/crypto.py", "wp-config.php",
                     "src/credentials.ts", "src/authorization.go", "config/.env.production"):
            with self.subTest(path=path):
                result = quality_policy.route([path])
                self.assertEqual("high", result["risk"])
                self.assertEqual("heavy", result["tier"])
                self.assertIn("engineering/shared-security", [m["id"] for m in result["modules"]])
        self.assertEqual("low", quality_policy.route(["src/tokenizer.py"])["risk"])

    def test_failure_missing_tool_and_timeout_cannot_pass(self):
        for check, status in [(self.check("raise SystemExit(9)"), "failed"),
                              ({"id": "absent", "argv": ["missing-quality-tool-123"]}, "missing_tool"),
                              (self.check("import time; time.sleep(10)", timeout=0.02), "timed_out")]:
            with self.subTest(status=status):
                result = self.run_checks([check])
                self.assertNotEqual("passed", result["status"])
                self.assertEqual(status, result["checks"][0]["status"])
                self.assertTrue(Path(result["report"]).exists())

    def test_partial_and_heavy_gates_are_honest(self):
        result = self.run_checks([self.check(), self.check(id="second")], only=["example"])
        self.assertEqual("incomplete", result["status"])
        check = self.check(tier="heavy", network=True)
        self.assertEqual("blocked", self.run_checks([check], risk="high")["checks"][0]["status"])
        self.assertEqual("passed", self.run_checks([check], risk="high", allow_heavy=True, allow_network=True)["status"])

    def test_cached_pass_invalidated_by_dirty_input(self):
        check = self.check(cache=True, complete_inputs=True, inputs=["src/cache.py"])
        self.run_checks([check])
        self.assertTrue(self.run_checks([check])["checks"][0]["cached"])
        (self.root / "src/cache.py").write_text("changed\n")
        self.assertNotIn("cached", self.run_checks([check])["checks"][0])

    def test_index_and_heavy_work_share_lock(self):
        with resource_lock(self.store, "index"), self.assertRaises(ValueError):
            with resource_lock(self.store, "heavy"):
                self.fail("overlap")

    def test_missing_measurement_fails_performance_budget(self):
        result = quality_checks.compare_performance({}, {}, {"lcp": {"maximum": 2500}})
        self.assertEqual("failed", result["status"])

    def test_nonfinite_performance_measurements_fail(self):
        for value in (float("nan"), float("inf"), True):
            result = quality_checks.compare_performance({"lcp": value}, {}, {"lcp": {"maximum": 2500}})
            self.assertEqual("failed", result["status"])

    def design_config(self):
        (self.root / "tokens.json").write_text(json.dumps({"tokens": {"--color": "#123456", "--space": "8px"}}))
        (self.root / "registry.json").write_text(json.dumps({"components": [
            {"name": "CacheCard", "source": "src/cache.py", "tokens": ["--color"]}]}))
        return {"version": 1, "design": {"tokens": "tokens.json", "registry": "registry.json"}}

    def test_token_cycles_and_missing_aliases_are_rejected(self):
        config = self.design_config()
        self.assertEqual("passed", design.check_tokens(self.root, config)["status"])
        (self.root / "tokens.json").write_text(json.dumps({"tokens": {
            "--a": "var(--b)", "--b": "var(--a)", "--c": "var(--absent)"}}))
        rules = {f["rule"] for f in design.check_tokens(self.root, config)["findings"]}
        self.assertEqual({"token-cycle", "unknown-token"}, rules)

    def test_css_nested_rules_and_comments(self):
        config = self.design_config()
        (self.root / "src/style.css").write_text("/* color: #ffffff */ @media(min-width: 500px) { .card { color: var(--color); padding: var(--space) } }")
        self.assertEqual("passed", design.check_css(self.root, config, ["src/style.css"])["status"])
        (self.root / "src/style.css").write_text("@media(min-width: 500px) { .card { color: #ffffff; padding: 13px!important; color: var(--missing) } }")
        rules = {f["rule"] for f in design.check_css(self.root, config, ["src/style.css"])["findings"]}
        self.assertTrue({"raw-color", "raw-scale", "important", "unknown-token", "duplicate-declaration"} <= rules)

    def test_svg_blocks_entities_and_active_content(self):
        config = self.design_config()
        source = self.root / "src/icon.svg"
        source.write_text('<svg viewBox="0 0 24 24" width="24" height="24"><path fill="currentColor"/></svg>')
        self.assertEqual("passed", design.check_svg(self.root, config, ["src/icon.svg"])["status"])
        source.write_text('<svg viewBox="0 0 24 24"><script>alert(1)</script><use href="https://example.com/x"/></svg>')
        self.assertEqual("failed", design.check_svg(self.root, config, ["src/icon.svg"])["status"])
        source.write_text('<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>')
        self.assertEqual("failed", design.check_svg(self.root, config, ["src/icon.svg"])["status"])

    def test_component_context_only_includes_relevant_tokens(self):
        from PIL import Image

        config = self.design_config()
        Image.new("RGB", (2, 2)).save(self.root / "card.png")
        config["design"]["registry"] = [{"name": "CacheCard", "source": "src/cache.py", "tokens": ["--color"],
                                          "screenshots": ["card.png"], "asset_preset": "hero-art",
                                          "responsive_rules": ["single column below 48rem"]}]
        chosen = design.context(self.root, config, "cache")
        self.assertEqual({"--color": "#123456"}, chosen["tokens"])
        component = chosen["components"][0]
        self.assertEqual(64, len(component["screenshot_evidence"][0]["sha256"]))
        self.assertIn("text_safe_zone", component["asset_presentation"])
        self.assertLess(chosen["estimated_tokens"], 3000)
        self.assertNotIn("screenshot_evidence", config["design"]["registry"][0])
        self.assertEqual("passed", design.check_components(self.root, config)["status"])

    def test_component_purpose_search_supports_russian_and_rejects_stale_reference(self):
        from context_economy.common import read_source
        from PIL import Image

        config = self.design_config()
        Image.new("RGB", (2, 2)).save(self.root / "card.png")
        item = {"name": "Card", "source": "src/cache.py", "keywords": ["карточка", "подписка", "оплата"],
                "screenshots": ["card.png"], "screenshot_sources": {"src/cache.py": read_source(self.root, "src/cache.py")["sha256"]}}
        config["design"]["registry"] = [item]
        self.assertEqual(design.context(self.root, config, "оплата подписка")["components"][0]["name"], "Card")
        (self.root / "src/cache.py").write_text("def cache(): return None # changed\n")
        with self.assertRaisesRegex(ValueError, "Screenshot source changed"):
            design.context(self.root, config, "оплата")

    def test_cli_status_and_bounded_route(self):
        cli = [sys.executable, str(INTEGRATION / "context_economy.py"), "--project", str(self.root),
               "--state-dir", str(Path(self.tmp.name) / "cli-state")]
        routed = subprocess.run(cli + ["guard-context", "--changed", "src/cache.py"], capture_output=True, text=True)
        self.assertEqual(0, routed.returncode, routed.stderr)
        self.assertLess(json.loads(routed.stdout)["estimated_tokens"], 1500)
        config = self.design_config()
        (self.root / "quality.json").write_text(json.dumps(config))
        checked = subprocess.run(cli + ["design-check", "tokens", "--config", "quality.json"], capture_output=True, text=True)
        self.assertEqual(0, checked.returncode, checked.stderr)

    def test_specialized_guards_and_permanent_router_budget(self):
        from context_economy.packing import estimate

        self.assertLessEqual(estimate((INTEGRATION / "quality/ROUTER.md").read_text()), 1000)
        for path, task, expected in [("assets/hero.avif", "ui", "design/assets"),
                                     ("styles/tokens.css", "ui", "design/tokens"),
                                     ("src/cache.go", "performance", "engineering/go-performance")]:
            result = quality_policy.route([path], task)
            self.assertIn(expected, [module["id"] for module in result["modules"]])
            self.assertLessEqual(len(result["modules"]), 3)
        for stack in ("nextjs", "wordpress"):
            self.assertLessEqual(quality_policy.route(["styles/ui.css"], "ui", stack=stack)["estimated_tokens"], 1500)

    @unittest.skipUnless(shutil.which("ast-grep"), "ast-grep unavailable")
    def test_ast_supported_stack_nodes(self):
        cases = {"item.go": "package main\nfunc Cache(x int) int { return x }\nfunc Run() { Cache(1) }\n",
                 "item.ts": "export function cache(x: number) { return x; }\ncache(1);\n",
                 "item.tsx": "export function Card() { return <div/>; }\nconst Page = () => <Card/>;\n",
                 "item.php": "<?php function cache($x) { return $x; } cache(1);\n"}
        for name, text in cases.items():
            with self.subTest(name=name):
                (self.root / "src" / name).write_text(text)
                parsed = retrieval.ast_map(self.store, ["src/" + name])
                self.assertTrue(parsed["files"][0]["symbols"])
                self.assertTrue(parsed["files"][0]["references"])

    def provider_args(self, **kwargs):
        args = {"command": "docs", "query": "parse stylesheet", "library": "/kozea/tinycss2",
                "library_version": "1.4.0", "limit": 2, "evidence_gap": "Need parser API signature",
                "preview_remote": False, "allow_remote": False, "config": "quality.json", "source": ["src"]}
        return SimpleNamespace(**{**args, **kwargs})

    def test_remote_permission_preview_and_cache(self):
        args = self.provider_args()
        with mock.patch.object(quality_providers, "capture") as capture:
            with self.assertRaises(ValueError):
                quality_providers.run(self.store, args)
            args.preview_remote = True
            self.assertFalse(quality_providers.run(self.store, args)["sent"])
            capture.assert_not_called()
            args.preview_remote, args.allow_remote = False, True
            capture.return_value = {"infoSnippets": [{"pageId": "https://example.com/docs", "content": "parser reference"}]}
            self.assertFalse(quality_providers.run(self.store, args)["cache_hit"])
            args.allow_remote = False
            self.assertTrue(quality_providers.run(self.store, args)["cache_hit"])
            self.assertEqual(1, capture.call_count)
            args.library_version = "2.0"
            with self.assertRaises(ValueError):
                quality_providers.run(self.store, args)

    def test_provider_budget_reserves_failed_attempt_cost(self):
        quality_providers.reserve_call(self.store, "rerank", .2, .3, 2)
        with self.assertRaises(ValueError):
            quality_providers.reserve_call(self.store, "rerank", .2, .3, 2)
        quality_providers.reserve_call(self.store, "docs", 0, 0, 1)
        with self.assertRaises(ValueError):
            quality_providers.reserve_call(self.store, "docs", 0, 0, 1)

    def test_semantic_scores_validate_identity_dimensions_and_nan(self):
        payload = {"candidates": [{"id": "a"}, {"id": "b"}], "max_results": 1}
        response = {"query_embedding": [1, 0], "candidates": [
            {"id": "a", "embedding": [0, 1]}, {"id": "b", "embedding": [1, 0]}]}
        ranked = quality_providers.rank_response(payload, response, "semantic-search")
        self.assertEqual("b", ranked["matches"][0]["id"])
        response["candidates"][1]["id"] = "invented"
        with self.assertRaises(ValueError):
            quality_providers.rank_response(payload, response, "semantic-search")
        with self.assertRaises(ValueError):
            quality_providers.cosine([float("nan")], [1])

    def test_assets_preserve_original_and_refuse_overwrite(self):
        from PIL import Image
        source = self.root / "art.png"
        Image.new("RGBA", (64, 48), (80, 100, 120, 255)).save(source)
        original = source.read_bytes()
        args = SimpleNamespace(source="art.png", output="prepared/portrait", preset="portrait", alt="Example portrait",
                               decorative=False, focal_x=.5, focal_y=.5, remove_background=False)
        output = assets.prepare(self.store, args)
        self.assertEqual("passed", output["status"])
        metadata = json.loads(Path(output["metadata"]).read_text())
        self.assertEqual({"avif", "webp"}, {v["format"] for v in metadata["variants"]})
        self.assertEqual(original, source.read_bytes())
        with self.assertRaises(ValueError):
            assets.prepare(self.store, args)
        args.output, args.alt = "other", ""
        with self.assertRaises(ValueError):
            assets.prepare(self.store, args)
