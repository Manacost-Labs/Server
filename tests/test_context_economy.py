import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

INTEGRATION = Path(__file__).resolve().parents[1] / "integrations/codex/subscription-savings"
sys.path.insert(0, str(INTEGRATION))

from context_economy import memory, packing, reporting, typesafe  # noqa: E402
from context_economy.common import Store, read_source  # noqa: E402


class EconomyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "project"
        self.root.mkdir()
        (self.root / "app.py").write_text("first\nsecond\nthird\n")
        self.store = Store(self.root, self.base / "state")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def note(self, text="Redirect cookie requires SameSite configuration"):
        return memory.add(self.store, text, "Reproduced with a local test", ["app.py"])

    def test_source_ranges_and_escape_rejected(self):
        self.assertEqual("second\n", read_source(self.root, "app.py:2:2")["text"])
        for spec in ("../outside", "app.py:0:1", "app.py:9:10"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                read_source(self.root, spec)
        (self.root / "escape").symlink_to(self.base)
        with self.assertRaises(ValueError):
            read_source(self.root, "escape/file")

    def test_sensitive_sources_rejected(self):
        (self.root / ".env").write_text("DO_NOT_READ=example")
        with self.assertRaises(ValueError):
            read_source(self.root, ".env")

    def test_fifo_and_oversize_sources_rejected_without_blocking(self):
        os.mkfifo(self.root / "pipe")
        with self.assertRaises(ValueError):
            read_source(self.root, "pipe")
        (self.root / "large").write_bytes(b"x" * (1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            read_source(self.root, "large")

    def test_state_symlink_rejected(self):
        (self.base / "alias").symlink_to(self.base / "state")
        with self.assertRaises(ValueError):
            Store(self.root, self.base / "alias")

    def test_memory_deduplicates_and_detects_dirty_changes(self):
        identifier = self.note()
        self.assertEqual(identifier, self.note())
        self.assertEqual(1, len(memory.search(self.store, "cookie")))
        (self.root / "app.py").write_text("changed without a commit\n")
        self.assertEqual([], memory.search(self.store, "cookie"))
        self.assertFalse(memory.inspect(self.store, identifier)["fresh"])

    def test_missing_source_and_expiry_invalidate(self):
        identifier = self.note()
        (self.root / "app.py").unlink()
        self.assertFalse(memory.inspect(self.store, identifier)["fresh"])
        with mock.patch.object(memory.time, "time", return_value=time.time() + 40 * 86400):
            self.assertEqual([], memory.search(self.store, "cookie"))

    def test_memory_project_isolation_and_unicode(self):
        self.note("Проверена авторизация и передача куки")
        self.assertEqual(1, len(memory.search(self.store, 'авторизация " OR *')))
        other = self.base / "other"
        other.mkdir()
        with Store(other, self.base / "state") as store:
            self.assertEqual([], memory.search(store, "авторизация"))

    def test_expired_note_requires_new_verification(self):
        identifier = self.note()
        with mock.patch.object(memory.time, "time", return_value=time.time() + 40 * 86400):
            self.assertEqual([], memory.search(self.store, "cookie"))
            self.assertNotEqual(identifier, self.note())

    def test_pack_preserves_required_context_and_reports_omissions(self):
        (self.root / "AGENTS.md").write_text("Preserve user files.\n")
        (self.root / "large.txt").write_text("optional content\n" * 1000)
        task = {"goal": "Fix cookie handling", "criteria": ["Tests pass"],
                "constraints": ["No deployment"]}
        result = packing.build(self.root, task, ["large.txt"], ["AGENTS.md"], [], 1800)
        self.assertIn("No deployment", result["text"])
        self.assertIn("Preserve user files.", result["text"])
        self.assertEqual(["large.txt"], result["omitted"])
        self.assertLessEqual(result["estimated_tokens"], 1800)
        with self.assertRaises(ValueError):
            packing.build(self.root, task, [], ["large.txt"], [], 100)

    def test_pack_does_not_cut_an_included_source(self):
        result = packing.build(self.root, {"goal": "Fix", "criteria": ["Pass"],
                                          "constraints": []}, ["app.py:2:3"], [], [], 1000)
        self.assertIn("second\\nthird\\n", result["text"])

    def test_pack_automatically_keeps_ancestor_instructions(self):
        (self.root / "AGENTS.md").write_text("Root rule")
        (self.root / "nested").mkdir()
        (self.root / "nested/AGENTS.md").write_text("Nested rule")
        (self.root / "nested/app.py").write_text("optional " * 1000)
        task = {"goal": "Fix", "criteria": ["Pass"], "constraints": []}
        result = packing.build(self.root, task, ["nested/app.py"], [], [], 700)
        document = json.loads(result["text"])
        self.assertEqual(["AGENTS.md", "nested/AGENTS.md"],
                         [item["path"] for item in document["required_sources"]])
        self.assertEqual(["nested/app.py"], result["omitted"])

    @staticmethod
    def response(payload, key, timeout):
        return {"model": "jev-test", "answers": {
            name: {"type": "choice", "choice": "relevant", "confidence": 0.95}
            for name in payload["questions"]},
            "usage": {"input_tokens": 100, "output_tokens": 10}}

    def test_typesafe_off_never_calls_transport(self):
        self.note()
        with mock.patch.object(typesafe, "transport") as transport:
            result = typesafe.rerank(self.store, "cookie", memory.search(self.store, "cookie"))
        transport.assert_not_called()
        self.assertEqual("off", result["status"])

    def test_typesafe_requires_explicit_remote_consent(self):
        with self.assertRaises(ValueError):
            typesafe.rerank(self.store, "cookie", [], mode="shadow")

    def test_typesafe_shadow_cache_and_changed_query(self):
        self.note()
        notes = memory.search(self.store, "cookie")
        with mock.patch.dict("os.environ", {"TYPESAFE_API_KEY": "test-only"}), \
                mock.patch.object(typesafe, "transport", side_effect=self.response) as call:
            first = typesafe.rerank(self.store, "cookie", notes, mode="shadow", allow_remote=True)
            second = typesafe.rerank(self.store, "cookie", notes, mode="shadow", allow_remote=True)
            typesafe.rerank(self.store, "redirect", notes, mode="shadow", allow_remote=True)
        self.assertEqual(notes, first["notes"])
        self.assertEqual("cache", second["status"])
        self.assertEqual(2, call.call_count)
        self.assertNotIn("app.py", json.dumps(call.call_args.args[0]))

    def test_typesafe_errors_and_daily_budget_fall_back(self):
        self.note()
        notes = memory.search(self.store, "cookie")
        with mock.patch.dict("os.environ", {"TYPESAFE_API_KEY": "test-only"}), \
                mock.patch.object(typesafe, "transport", side_effect=TimeoutError) as call:
            first = typesafe.rerank(self.store, "cookie", notes, mode="active", allow_remote=True,
                                    daily_calls=1)
            second = typesafe.rerank(self.store, "again", notes, mode="active", allow_remote=True,
                                     daily_calls=1)
        self.assertEqual(notes, first["notes"])
        self.assertEqual("fallback", first["status"])
        self.assertEqual("daily_limit", second["status"])
        self.assertEqual(1, call.call_count)

    def test_typesafe_malformed_response_never_changes_selection(self):
        self.note()
        notes = memory.search(self.store, "cookie")
        with mock.patch.dict("os.environ", {"TYPESAFE_API_KEY": "test-only"}), \
                mock.patch.object(typesafe, "transport", return_value={"answers": {}}):
            result = typesafe.rerank(self.store, "cookie", notes, mode="active", allow_remote=True)
        self.assertEqual("fallback", result["status"])
        self.assertEqual(notes, result["notes"])

    def test_typesafe_uncertainty_keeps_order_and_active_ranks(self):
        self.note("Cookie first explanation")
        self.note("Cookie second explanation")
        notes = memory.search(self.store, "cookie")

        def answers(payload, key, timeout):
            result = self.response(payload, key, timeout)
            result["answers"]["candidate_0"].update(choice="irrelevant", confidence=0.95)
            return result

        with mock.patch.dict("os.environ", {"TYPESAFE_API_KEY": "test-only"}), \
                mock.patch.object(typesafe, "transport", side_effect=answers):
            result = typesafe.rerank(self.store, "cookie", notes, mode="active", allow_remote=True)
            uncertain = typesafe.rerank(self.store, "cookie", notes, mode="active", allow_remote=True,
                                        confidence=0.99)
        self.assertEqual(list(reversed(notes)), result["notes"])
        self.assertEqual(notes, uncertain["notes"])

    def test_typesafe_payload_budget_and_secret_block_before_network(self):
        self.note()
        notes = memory.search(self.store, "cookie")
        with self.assertRaises(ValueError):
            typesafe.payload_for("x" * 8001, notes)
        notes[0]["text"] = "api_key=" + "example-private-value"
        with self.assertRaises(ValueError):
            typesafe.payload_for("cookie", notes)

    def test_typesafe_rejects_redirect_and_nonfinite_confidence(self):
        with self.assertRaises(ValueError):
            typesafe.NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://example.org")
        with self.assertRaises(ValueError):
            typesafe.validate({"answers": {"a": {"choice": "relevant", "confidence": float("nan")}}}, ["a"])

    def test_usage_includes_failed_attempts_and_preserves_unknowns(self):
        base = {"task_id": "cookie", "variant": "local", "model": "gpt-6-astra",
                "effort": "medium", "speed": "standard", "dataset": "demo-v1",
                "elapsed_seconds": 10, "input_tokens": 100, "output_tokens": 20}
        reporting.record(self.store, dict(base, attempt_id="one", success=False))
        reporting.record(self.store, dict(base, attempt_id="two", success=True))
        row = reporting.summary(self.store)[0]
        self.assertEqual(240, row["tokens_per_completed_task"])
        self.assertIsNone(row["total_api_cost_usd"])
        with self.assertRaises(ValueError):
            reporting.record(self.store, dict(base, attempt_id="two", success=True))

    def test_usage_rejects_invalid_numbers(self):
        base = {"task_id": "fix", "variant": "local", "effort": "medium", "speed": "standard",
                "dataset": "v1", "model": "gpt-6-astra", "attempt_id": "invalid", "success": False}
        for number in (float("nan"), float("inf"), -1, True, 1.5):
            with self.subTest(number=number), self.assertRaises(ValueError):
                reporting.record(self.store, dict(base, input_tokens=number))
        with self.assertRaises(ValueError):
            reporting.record(self.store, dict(base, input_tokens=10, cached_input_tokens=11))

    def test_end_to_end_report_includes_preparation_models(self):
        base = {"task_id": "fix", "variant": "local", "effort": "medium", "speed": "standard",
                "dataset": "v1", "input_tokens": 100, "output_tokens": 20}
        reporting.record(self.store, dict(base, attempt_id="prep", model="gpt-5.6-terra", success=False))
        reporting.record(self.store, dict(base, attempt_id="solve", model="gpt-6-astra", success=True))
        report = reporting.summary(self.store, end_to_end=True)[0]
        self.assertEqual(240, report["tokens_per_completed_task"])
        self.assertEqual(2, len(report["model_settings"]))

    def test_cli_pack_and_remote_preview_are_local(self):
        self.note()
        (self.root / "task.json").write_text(json.dumps({"goal": "Fix cookie", "criteria": ["Pass"],
                                                       "constraints": ["No deployment"]}))
        base = [sys.executable, str(INTEGRATION / "context_economy.py"), "--project", str(self.root),
                "--state-dir", str(self.base / "state")]
        result = subprocess.run(base + ["pack", "--task", "task.json", "--source", "app.py", "--query", "cookie"],
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["No deployment"], json.loads(result.stdout)["task"]["constraints"])
        preview = subprocess.run(base + ["recall", "cookie", "--preview-remote"], capture_output=True, text=True)
        self.assertEqual(0, preview.returncode, preview.stderr)
        self.assertEqual("choice", json.loads(preview.stdout)["questions"]["candidate_0"]["type"])
        self.assertEqual(0, self.store.db.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0])

    def test_cli_gate_preserves_nonzero_exit_and_exact_log(self):
        result = subprocess.run(
            [sys.executable, str(INTEGRATION / "context_economy.py"), "--project", str(self.root),
             "--state-dir", str(self.base / "state"), "gate", "--", sys.executable, "-c",
             "import sys; print('prefix'); print('ERROR: cookie failure'); sys.exit(7)"],
            capture_output=True, text=True)
        self.assertEqual(7, result.returncode, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual("prefix\nERROR: cookie failure\n", Path(receipt["log"]).read_text())
        self.assertIn("ERROR", receipt["preview"])

    def test_gate_timeout_and_bounded_preview_preserve_tail(self):
        from context_economy import output

        result = output.run(self.store, [sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.05)
        self.assertEqual(124, result["exit_code"])
        result = output.run(self.store, [sys.executable, "-c",
                            "print('noise' * 5000); print('FINAL FAILURE')"], preview_chars=300)
        self.assertLessEqual(len(result["preview"]), 300)
        self.assertIn("FINAL FAILURE", result["preview"])


if __name__ == "__main__":
    unittest.main()
