import argparse
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integrations/codex/subscription-savings"
sys.path.insert(0, str(INTEGRATION))

from context_economy import (  # noqa: E402
    assist,
    briefs,
    focus,
    meter,
    output,
    pilot,
    remote,
    repetition,
)
from context_economy.common import Store, encode  # noqa: E402


class EconomyFiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "project"
        self.root.mkdir()
        (self.root / "AGENTS.md").write_text("MANDATORY LOCAL POLICY\n")
        (self.root / "task.json").write_text(encode({"goal": "Explain readiness", "criteria": ["Preserve failures"],
                                                   "constraints": ["No production changes"]}))
        self.source = self.root / "service.py"
        self.source.write_text('def readiness(worker):\n    return 200 if worker else 503\n')
        (self.root / "docs.txt").write_text("Readiness needs a healthy worker.\nMutation requires authentication.\n" + "History.\n" * 100)
        self.store = Store(self.root, self.base / "state")
        self.ledger = remote.Ledger(self.base / "ledger")
        self.session = self.base / "rollout.jsonl"
        self.session.write_text(encode({"type": "turn_context", "payload": {"model": "gpt-6-astra", "effort": "high"}}) + "\n")
        self.append_usage(100, 10)

    def tearDown(self):
        self.store.close()
        self.ledger.close()
        self.temp.cleanup()

    def append(self, value):
        with self.session.open("a") as stream:
            stream.write(encode(value) + "\n")

    def append_usage(self, inputs, outputs):
        self.append({"type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": inputs, "output_tokens": outputs,
                                  "cached_input_tokens": inputs // 2, "reasoning_output_tokens": outputs // 2}}}})

    def gemma(self, quote="Readiness needs a healthy worker."):
        return {"choices": [{"finish_reason": "stop", "message": {"content": encode({
            "items": [{"source_id": "s0", "quote": quote, "note": "Unverified reference"}], "uncertainties": []})}}],
                "usage": {"cost": 0.00002}}

    def helper(self, function, args, response=None, effect=None):
        with mock.patch.object(remote, "Ledger", return_value=self.ledger), \
                mock.patch.object(self.ledger, "close"), \
                mock.patch.object(remote, "api_key", return_value="synthetic-key"), \
                mock.patch.object(remote, "send", return_value=response or self.gemma(), side_effect=effect):
            return function(self.store, args)

    def brief_args(self, **kwargs):
        return argparse.Namespace(**dict({"source": ["docs.txt"], "purpose": "documentation", "allow_remote": True,
                                          "preview_remote": False, "daily_budget_usd": 1, "api_timeout": 2,
                                          "budget": 12000}, **kwargs))

    def assist_args(self):
        (self.root / "facts.json").write_text(encode([{"source": "docs.txt", "quote": "Mutation requires authentication."}]))
        return argparse.Namespace(task="task.json", source=["docs.txt"], required=[], facts="facts.json",
                                  purpose="context", budget=12000, provider="gemma", mode="active",
                                  preview_remote=False, allow_remote=True, daily_budget_usd=1, api_timeout=2)

    def test_meter_uses_deltas_and_preserves_subsets(self):
        meter.start(self.store, "task-1", self.session)
        self.append({"type": "response_item", "payload": {"type": "function_call", "arguments": "PRIVATE PROMPT"}})
        self.append_usage(160, 30)
        value = meter.report(self.store, "task-1", finish=True)
        self.assertEqual(60, value["input_tokens"])
        self.assertEqual(20, value["output_tokens"])
        self.assertEqual(30, value["cached_input_tokens"])
        self.assertEqual(1, value["tool_calls"])
        self.assertIsNone(value["codex_credits"])
        stored = self.store.db.execute("SELECT body FROM meter_runs").fetchone()[0]
        self.assertNotIn("PRIVATE PROMPT", stored)

    def test_meter_no_new_usage_is_unknown_not_zero(self):
        meter.start(self.store, "task-1", self.session)
        self.assertIsNone(meter.report(self.store, "task-1")["input_tokens"])

    def test_meter_partial_event_consumed_once(self):
        meter.start(self.store, "task-1", self.session)
        event = encode({"type": "response_item", "payload": {"type": "custom_tool_call"}})
        with self.session.open("a") as stream:
            stream.write(event[:20])
        self.assertEqual(0, meter.report(self.store, "task-1")["tool_calls"])
        with self.session.open("a") as stream:
            stream.write(event[20:] + "\n")
        self.assertEqual(1, meter.report(self.store, "task-1")["tool_calls"])
        self.assertEqual(1, meter.report(self.store, "task-1")["tool_calls"])

    def test_meter_counter_reset_stays_unknown(self):
        meter.start(self.store, "task-1", self.session)
        self.append_usage(5, 1)
        self.append_usage(500, 100)
        self.assertIsNone(meter.report(self.store, "task-1")["input_tokens"])

    def test_meter_baseline_uses_latest_model_even_when_previously_seen(self):
        for model in ("gpt-5.6-terra", "gpt-6-astra", "gpt-5.6-terra"):
            self.append({"type": "turn_context", "payload": {"model": model, "effort": "medium"}})
        meter.start(self.store, "task-1", self.session)
        self.assertEqual([{"model": "gpt-5.6-terra", "effort": "medium"}], meter.report(self.store, "task-1")["model_settings"])

    def test_meter_finish_is_idempotent_and_excludes_later_work(self):
        meter.start(self.store, "task-1", self.session)
        self.append_usage(140, 20)
        first = meter.report(self.store, "task-1", finish=True)
        self.append_usage(200, 100)
        self.assertEqual(first, meter.report(self.store, "task-1", finish=True))

    def test_meter_bounds_incremental_scan(self):
        meter.start(self.store, "task-1", self.session)
        with self.session.open("a") as stream:
            stream.write("x" * 200)
        with mock.patch.object(meter, "WINDOW", 100), self.assertRaisesRegex(ValueError, "8 MiB"):
            meter.report(self.store, "task-1")

    def test_meter_rejects_symlink_replacement_and_duplicate_task(self):
        link = self.base / "alias.jsonl"
        link.symlink_to(self.session)
        with self.assertRaises(ValueError):
            meter.start(self.store, "bad", link)
        meter.start(self.store, "task-1", self.session)
        with self.assertRaises(ValueError):
            meter.start(self.store, "task-2", self.session)
        self.session.write_text("")
        with self.assertRaisesRegex(ValueError, "truncated"):
            meter.report(self.store, "task-1")

    def test_cancel_recovers_missing_session_without_manufacturing_metrics(self):
        meter.start(self.store, "task-1", self.session)
        self.session.unlink()
        meter.cancel(self.store, "task-1")
        self.assertTrue(meter.report(self.store, "task-1")["cancelled"])
        self.assertIsNone(meter.active_id(self.store))
        with self.assertRaises(ValueError):
            pilot.measured(self.store, {"evidence": "Incomplete check"}, "task-1")

    def test_remote_meter_includes_invalid_paid_response_and_cache_is_free(self):
        meter.start(self.store, "task-1", self.session)
        meter.bind(self.store, "task-1")
        self.helper(briefs.run, self.brief_args())
        self.helper(briefs.run, self.brief_args(), effect=AssertionError("No second request"))
        result = meter.report(self.store, "task-1")
        self.assertEqual(0.00002, result["helper_api_cost_usd"])
        self.assertEqual(1, result["remote_calls"])
        self.assertEqual(1, result["cache_hits"])
        self.source.write_text("unrelated\n" * 100)
        self.helper(briefs.run, self.brief_args(source=["service.py"]), response={"usage": {"cost": 0.00003}})
        self.assertEqual(0.00005, meter.report(self.store, "task-1")["helper_api_cost_usd"])

    def test_remote_unknown_failure_cost_not_zero(self):
        meter.start(self.store, "task-1", self.session)
        meter.bind(self.store, "task-1")
        self.helper(briefs.run, self.brief_args(), effect=OSError("offline"))
        self.assertIsNone(meter.report(self.store, "task-1")["helper_api_cost_usd"])

    def test_pilot_imports_measured_settings_but_not_guessed_api_total(self):
        meter.start(self.store, "task-1", self.session)
        self.append_usage(150, 20)
        meter.report(self.store, "task-1", finish=True)
        value = pilot.measured(self.store, {"evidence": "Tests passed"}, "task-1")
        self.assertEqual("astra", value["model"])
        self.assertEqual("high", value["effort"])
        self.assertEqual("unknown", value["speed"])
        self.assertEqual(50, value["input_tokens"])
        self.assertIsNone(value["api_cost_usd"])

    def test_meter_import_requires_quality_evidence_and_actual_model(self):
        meter.start(self.store, "task-1", self.session)
        meter.report(self.store, "task-1", finish=True)
        for outcome in ({}, {"evidence": "Tests pass", "model": "luna"}):
            with self.assertRaises(ValueError):
                pilot.measured(self.store, outcome, "task-1")

    def test_missing_critical_fact_restores_original_fragment(self):
        value = self.helper(assist.run, self.assist_args())
        self.assertEqual(["docs.txt"], value["restored_critical_sources"])
        self.assertIn("Mutation requires authentication.", encode(value["packet"]["context"]))
        self.assertEqual(["No production changes"], value["packet"]["task"]["constraints"])

    def test_present_fact_needs_no_restore(self):
        value = self.helper(assist.run, self.assist_args(), self.gemma("Mutation requires authentication."))
        self.assertEqual([], value["restored_critical_sources"])

    def test_fake_critical_fact_rejected_before_paid_request(self):
        args = self.assist_args()
        (self.root / "facts.json").write_text(encode([{"source": "docs.txt", "quote": "Invented requirement"}]))
        with mock.patch.object(remote, "Ledger", side_effect=AssertionError), self.assertRaises(ValueError):
            assist.run(self.store, args)

    def test_facts_stale_after_remote_call_rejected(self):
        args = self.assist_args()

        def change(*_):
            (self.root / "facts.json").write_text("[]")
            return self.gemma()

        with self.assertRaises(assist.StaleSource):
            self.helper(assist.run, args, effect=change)

    def test_brief_cache_is_per_file_version_and_purpose(self):
        args = self.brief_args()
        self.assertEqual("remote", self.helper(briefs.run, args)["references"][0]["usage"]["status"])
        self.assertEqual("file_cache", self.helper(briefs.run, args, effect=AssertionError)["references"][0]["usage"]["status"])
        with (self.root / "docs.txt").open("a") as stream:
            stream.write("A new contract.\n")
        self.assertEqual("remote", self.helper(briefs.run, args)["references"][0]["usage"]["status"])
        args.purpose = "memory"
        self.assertEqual("remote", self.helper(briefs.run, args)["references"][0]["usage"]["status"])

    def test_brief_preview_and_local_fallback_never_request(self):
        with mock.patch.object(remote, "Ledger", side_effect=AssertionError):
            preview = briefs.run(self.store, self.brief_args(preview_remote=True))
            self.assertNotIn("MANDATORY LOCAL", encode(preview))
            self.assertNotIn(str(self.root), encode(preview))
            local = briefs.run(self.store, self.brief_args(allow_remote=False))
            self.assertIsNotNone(local["references"][0]["original"])

    def test_brief_unchanged_file_remains_cached_when_other_file_changes(self):
        (self.root / "other.txt").write_text("Readiness needs a healthy worker.\n" + "History.\n" * 100)
        args = self.brief_args(source=["docs.txt", "other.txt"])
        self.helper(briefs.run, args)
        (self.root / "other.txt").write_text("Readiness needs a healthy worker.\n" + "Updated.\n" * 100)
        result = self.helper(briefs.run, args)
        self.assertEqual(["file_cache", "remote"], [r["usage"]["status"] for r in result["references"]])

    def test_brief_changed_source_after_request_rejected(self):
        def change(*_):
            (self.root / "docs.txt").write_text("Changed")
            return self.gemma()
        with self.assertRaisesRegex(ValueError, "source changed"):
            self.helper(briefs.run, self.brief_args(), effect=change)

    def test_brief_secret_path_and_oversized_input_rejected(self):
        (self.root / ".env").write_text("private")
        with self.assertRaises(ValueError):
            briefs.run(self.store, self.brief_args(source=[".env"]))
        (self.root / "docs.txt").write_text("x" * 24001)
        with self.assertRaises(ValueError):
            briefs.run(self.store, self.brief_args())

    def test_brief_does_not_summarize_instruction_files(self):
        with mock.patch.object(remote, "Ledger", side_effect=AssertionError), self.assertRaisesRegex(ValueError, "verbatim"):
            briefs.run(self.store, self.brief_args(source=["AGENTS.md"]))

    def test_repeat_read_changes_with_source_hypothesis_and_task(self):
        self.assertIsNone(repetition.observe(self.store, "read", "service.py:1:2", "version-1"))
        self.assertIsNotNone(repetition.observe(self.store, "read", "service.py:1:2", "version-1"))
        self.assertIsNone(repetition.observe(self.store, "read", "service.py:1:2", "version-2"))
        self.assertIsNone(repetition.observe(self.store, "read", "service.py:1:2", "version-1", "new evidence"))
        meter.start(self.store, "new-task", self.session)
        meter.bind(self.store, "new-task")
        self.assertIsNone(repetition.observe(self.store, "read", "service.py:1:2", "version-1"))

    def test_gate_repeats_do_not_suppress_command_or_exit_code(self):
        argv = [sys.executable, "-c", "import sys; print('ERROR synthetic failure'); sys.exit(3)"]
        first = output.run(self.store, argv, preview_chars=500)
        second = output.run(self.store, argv, preview_chars=500)
        self.assertEqual(3, second["exit_code"])
        self.assertIn("ERROR synthetic failure", Path(second["log"]).read_text())
        self.assertIsNone(first["repetition"])
        self.assertIsNotNone(second["repetition"])
        self.assertIsNone(output.run(self.store, argv, preview_chars=500, hypothesis="Changed parser")["repetition"])

    def focus_args(self):
        return argparse.Namespace(task="task.json", source=["service.py:1:2"], required=[],
                                  search_in=["service.py"], query="readiness", budget=3000)

    def test_probe_fallback_preserves_changed_code_and_policy(self):
        with mock.patch.object(focus.subprocess, "run", side_effect=FileNotFoundError):
            result = focus.run(self.store, self.focus_args())
        self.assertEqual("fallback", result["status"])
        required = result["packet"]["required_sources"]
        self.assertTrue(any(s["source"] == "service.py:1:2" for s in required))
        self.assertTrue(any(s["source"] == "AGENTS.md" for s in required))

    def test_probe_only_receives_selected_snapshots_and_maps_valid_lines(self):
        def search(argv, **kwargs):
            staging = Path(argv[3])
            self.assertEqual(["service.py"], [p.name for p in staging.iterdir()])
            kwargs["stdout"].write(encode({"results": [{"file": str(staging / "service.py"), "lines": [1, 2]}]}).encode())
            return subprocess.CompletedProcess(argv, 0)
        with mock.patch.object(focus.subprocess, "run", side_effect=search):
            result = focus.run(self.store, self.focus_args())
        self.assertEqual("probe", result["status"])
        self.assertEqual([], result["candidate_sources"])  # The pinned function must not be repeated.
        self.assertLessEqual(result["estimated_tokens"], 3000)

    def test_malformed_probe_response_falls_back_without_omitting_pinned_code(self):
        def search(argv, **kwargs):
            kwargs["stdout"].write(b"[]")
            return subprocess.CompletedProcess(argv, 0)
        with mock.patch.object(focus.subprocess, "run", side_effect=search):
            result = focus.run(self.store, self.focus_args())
        self.assertEqual("fallback", result["status"])
        self.assertIn("return 200 if worker else 503", encode(result["packet"]))

    def test_search_rejects_server_root_symlink_and_large_inventory(self):
        with self.assertRaises(ValueError):
            focus.candidates(self.root, ["."])
        (self.root / "alias").symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(ValueError):
            focus.candidates(self.root, ["alias"])
        directory = self.root / "many"
        directory.mkdir()
        for i in range(101):
            (directory / f"f{i}.py").write_text("pass\n")
        with self.assertRaisesRegex(ValueError, "100"):
            focus.candidates(self.root, ["many"])

    def test_cli_read_hints_on_second_read(self):
        argv = [sys.executable, str(INTEGRATION / "context_economy.py"), "--project", str(self.root),
                "--state-dir", str(self.base / "cli"), "read", "--source", "service.py:1:2"]
        first = json.loads(subprocess.run(argv, check=True, capture_output=True, text=True).stdout)
        second = json.loads(subprocess.run(argv, check=True, capture_output=True, text=True).stdout)
        self.assertIsNone(first["repetition"])
        self.assertEqual(2, second["repetition"]["observations"])
        self.assertEqual(first["text"], second["text"])


if __name__ == "__main__":
    unittest.main()
