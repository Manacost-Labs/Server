import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

INTEGRATION = Path(__file__).resolve().parents[1] / "integrations/codex/subscription-savings"
sys.path.insert(0, str(INTEGRATION))

import benchmark  # noqa: E402
from context_economy import briefs, meter, remote  # noqa: E402
from context_economy.common import Store, encode  # noqa: E402


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root, self.root / "state")
        self.a = self.session("a", 100, 10)
        self.b = self.session("b", 200, 20)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def session(self, name, inp, out):
        p = self.root / (name + ".jsonl")
        self.usage(p, inp, out)
        return p

    def usage(self, path, inp, out):
        with path.open("a") as stream:
            stream.write(encode({"type": "event_msg", "payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": inp, "cached_input_tokens": 0,
                                      "output_tokens": out, "reasoning_output_tokens": 0}}}}) + "\n")

    def test_parallel_sessions_and_explicit_helper_binding(self):
        meter.start(self.store, "a", self.a)
        meter.start(self.store, "b", self.b)
        meter.bind(self.store, "a")
        meter.remote_event(self.store, "remote", {"cost": .01, "prompt_tokens": 12, "completion_tokens": 3})
        meter.bind(self.store, "b")
        meter.remote_event(self.store, "remote", {"cost": .02, "prompt_tokens": 8, "completion_tokens": 2})
        self.usage(self.a, 130, 15)
        self.usage(self.b, 250, 25)
        a, b = meter.report(self.store, "a"), meter.report(self.store, "b")
        self.assertEqual((a["input_tokens"], b["input_tokens"]), (30, 50))
        self.assertEqual((a["helper_api_cost_usd"], b["helper_api_cost_usd"]), (.01, .02))
        self.assertEqual((a["all_model_input_tokens"], b["all_model_input_tokens"]), (42, 58))

    def test_unbound_helper_is_never_guessed_even_with_one_task(self):
        meter.start(self.store, "a", self.a)
        meter.remote_event(self.store, "remote", {"cost": .03})
        result = meter.report(self.store, "a")
        self.assertEqual(result["remote_calls"], 0)
        self.assertEqual(result["unattributed_events"], 1)
        self.assertIsNone(result["helper_api_cost_usd"])
        self.assertIsNone(result["all_model_input_tokens"])

    def test_unknown_binding_rejected_before_work(self):
        with self.assertRaises(ValueError):
            meter.bind(self.store, "missing")
        meter.start(self.store, "a", self.a)
        meter.cancel(self.store, "a")
        with self.assertRaises(ValueError):
            meter.bind(self.store, "a")

    def test_helper_codex_session_counts_and_cannot_be_shared(self):
        meter.start(self.store, "a", self.a, from_task_start=True)
        meter.attach(self.store, "a", self.b, "compaction")
        with self.assertRaises(ValueError):
            meter.start(self.store, "b", self.b)
        self.usage(self.a, 130, 15)
        self.usage(self.b, 240, 30)
        result = meter.report(self.store, "a", finish=True, coverage_evidence="All task phases and helpers accounted for")
        self.assertEqual(result["input_tokens"], 70)
        self.assertEqual(result["output_tokens"], 15)
        self.assertEqual(result["coverage"]["status"], "declared-complete")
        self.assertEqual(len(result["codex_components"]), 2)
        meter.start(self.store, "b", self.b)

    def test_partial_interval_cannot_be_promoted_by_finish_attestation(self):
        meter.start(self.store, "a", self.a)
        self.usage(self.a, 130, 15)
        result = meter.report(self.store, "a", finish=True, coverage_evidence="All helpers included in this interval")
        self.assertEqual(result["coverage"]["status"], "partial-or-unknown")

    def test_hardlink_session_alias_cannot_double_count(self):
        alias = self.root / "alias.jsonl"
        os.link(self.a, alias)
        meter.start(self.store, "a", self.a)
        with self.assertRaises(ValueError):
            meter.start(self.store, "alias", alias)

    def test_concurrent_claims_cannot_double_count_one_session(self):
        barrier = threading.Barrier(2)

        def claim(identifier):
            with Store(self.root, self.root / "state") as store:
                barrier.wait(timeout=10)
                try:
                    meter.start(store, identifier, self.a)
                    return True
                except ValueError:
                    return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ("a", "other")))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM meter_runs WHERE active=1").fetchone()[0], 1)

    def test_empty_session_baseline_measures_first_usage(self):
        empty = self.root / "empty.jsonl"
        empty.touch()
        meter.start(self.store, "a", empty)
        self.usage(empty, 90, 8)
        self.assertEqual(meter.report(self.store, "a")["input_tokens"], 90)

    def test_failed_helper_keeps_total_usage_unknown(self):
        meter.start(self.store, "a", self.a, from_task_start=True)
        meter.bind(self.store, "a")
        meter.remote_event(self.store, "failed")
        self.usage(self.a, 150, 20)
        result = meter.report(self.store, "a", finish=True, coverage_evidence="All phases attempted and recorded")
        self.assertIsNone(result["all_model_input_tokens"])
        self.assertIsNone(result["helper_api_cost_usd"])
        self.assertEqual(result["coverage"]["status"], "partial-or-unknown")

    def test_cli_environment_binds_command_to_correct_parallel_task(self):
        meter.start(self.store, "a", self.a)
        meter.start(self.store, "b", self.b)
        command = [sys.executable, str(INTEGRATION / "context_economy.py"), "--project", str(self.root),
                   "--state-dir", str(self.root / "state"), "gate", "--", sys.executable, "-c", "print('ok')"]
        run = subprocess.run(command, env={**os.environ, "CODEX_ECONOMY_TASK_ID": "b"},
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(meter.report(self.store, "a")["commands"], 0)
        self.assertEqual(meter.report(self.store, "b")["commands"], 1)
        marker = self.root / "not-run"
        command[-1] = "from pathlib import Path; Path('not-run').touch()"
        run = subprocess.run(command, env={**os.environ, "CODEX_ECONOMY_TASK_ID": "missing"}, capture_output=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertFalse(marker.exists())

    def test_legacy_active_measurement_migrates_without_losing_history(self):
        self.store.db.executescript('CREATE TABLE meter_runs (id TEXT PRIMARY KEY, active INTEGER, body TEXT);'
                                   'CREATE UNIQUE INDEX one_active_meter ON meter_runs(active) WHERE active=1;')
        snapshot = meter.session_read(self.a)
        body = {"started": 1, "session": str(self.a), "baseline": snapshot, "latest": snapshot,
                "baseline_events": snapshot["usage_events"]}
        self.store.db.execute("INSERT INTO meter_runs VALUES('legacy',1,?)", (encode(body),))
        self.store.db.commit()
        meter.start(self.store, "b", self.b)
        self.usage(self.a, 150, 20)
        self.assertEqual(meter.report(self.store, "legacy")["input_tokens"], 50)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM meter_runs").fetchone()[0], 2)

    def test_late_event_is_visible_and_invalidates_complete_coverage(self):
        meter.start(self.store, "a", self.a, from_task_start=True)
        meter.bind(self.store, "a")
        self.usage(self.a, 130, 15)
        meter.report(self.store, "a", finish=True, coverage_evidence="All work included before finish")
        meter.remote_event(self.store, "remote", {"cost": .01})
        value = meter.report(self.store, "a")
        self.assertEqual(value["late_events"], 1)
        self.assertEqual(value["helper_api_cost_usd"], .01)
        self.assertEqual(value["coverage"]["status"], "partial-or-unknown")

    def brief(self, text, quote, **extra):
        (self.root / "docs.txt").write_text(text)
        args = argparse.Namespace(source=["docs.txt"], purpose="documentation", allow_remote=True,
                                  preview_remote=False, daily_budget_usd=1, api_timeout=2, budget=12000,
                                  min_reduction=.15, facts=extra.get("facts"))
        response = {"choices": [{"finish_reason": "stop", "message": {"content": encode({
            "items": [{"source_id": "s0", "quote": quote, "note": "Unverified draft"}], "uncertainties": []})}}],
                    "usage": {"cost": .001}}
        with mock.patch.object(remote, "Ledger") as ledger, mock.patch.object(remote, "api_key", return_value="test"), \
                mock.patch.object(remote, "send", return_value=response) as send:
            ledger.return_value.reserve.return_value = "reservation"
            result = briefs.run(self.store, args)
            if len(text.encode()) < 600:
                send.assert_not_called()
            return result

    def test_expanding_brief_retains_original(self):
        text = "The result is a hypothesis, not a verified fact. " * 16
        result = self.brief(text, text)
        self.assertFalse(result["reduction"]["applied"])
        self.assertEqual(result["references"][0]["original"], text)

    def test_small_source_skips_paid_preparation(self):
        result = self.brief("A short source.", "A short source.")
        self.assertEqual(result["references"][0]["usage"]["status"], "skipped-small-source")
        self.assertFalse(result["reduction"]["applied"])

    def test_large_source_uses_smaller_complete_packet(self):
        text = "Timeouts can occur.\n" + "Historical details.\n" * 220
        result = self.brief(text, "Timeouts can occur.")
        self.assertTrue(result["reduction"]["applied"])
        self.assertLess(len(encode(result).encode()), len(text.encode()) * .85)
        self.assertIsNone(result["references"][0]["original"])

    def test_missing_required_uncertainty_restores_source(self):
        text = "Timeouts can occur. This is only a hypothesis.\n" + "History.\n" * 300
        (self.root / "facts.json").write_text(encode([{"source": "docs.txt", "quote": "This is only a hypothesis."}]))
        result = self.brief(text, "Timeouts can occur.", facts="facts.json")
        self.assertEqual(result["references"][0]["original"], text)
        self.assertFalse(result["reduction"]["applied"])


class AssessmentTests(unittest.TestCase):
    def pair(self, case="a", dataset="real"):
        row = json.loads((INTEGRATION / "benchmark/baseline.template.json").read_text())
        row.update(schema=2, case_id=case, task="Investigate retries", source_repository="api", source_commit="a" * 40,
                   model="gpt-5.6-terra", reasoning_effort="medium", speed="standard", dataset=dataset,
                   measurement="observed", evidence="Counter and acceptance artifacts")
        row.update({k: 0 for k in benchmark.METRICS})
        row.update(input_tokens=100, output_tokens=20, elapsed_seconds=10, model_launches=1)
        row["tests"] = {"passed": True, "command": "test", "evidence": "Passed output"}
        row["quality"] = {"accepted": True, "criteria": "Retry preserves contract", "rework_notes": "None"}
        row["coverage"] = {"from_task_start": True, "helpers_included": True, "compaction_included": True,
                           "finished": True, "evidence": "Complete intervals and helper ledger"}
        other = copy.deepcopy(row)
        other.update(variant="economy", input_tokens=70)
        return row, other

    def test_requires_ten_real_complete_distinct_pairs(self):
        self.assertEqual(benchmark.assess([self.pair()])["status"], "insufficient-evidence")
        self.assertEqual(benchmark.assess([self.pair(str(i), "synthetic") for i in range(10)])["eligible_pairs"], 0)
        with self.assertRaises(ValueError):
            benchmark.assess([self.pair(), self.pair()])

    def test_reduction_does_not_override_failed_quality_or_rework(self):
        pairs = [self.pair(str(i)) for i in range(10)]
        self.assertEqual(benchmark.assess(pairs)["status"], "pilot-target-met")
        pairs[0][1]["tests"]["passed"] = False
        self.assertEqual(benchmark.assess(pairs)["status"], "pilot-target-not-met")
        pairs[0][1]["tests"]["passed"] = True
        pairs[0][1]["rework_count"] = 1
        self.assertEqual(benchmark.assess(pairs)["status"], "pilot-target-not-met")

    def test_partial_unknown_and_legacy_records_do_not_qualify(self):
        for field in ("helpers_included", "compaction_included", "from_task_start", "finished"):
            pair = self.pair()
            pair[1]["coverage"][field] = False
            self.assertEqual(benchmark.assess([pair])["eligible_pairs"], 0)
        pair = self.pair()
        for row in pair:
            row["schema"] = 1
            del row["coverage"]
        self.assertEqual(benchmark.assess([pair])["eligible_pairs"], 0)

    def test_cached_and_reasoning_subsets_are_not_double_counted(self):
        pairs = [self.pair(str(i)) for i in range(10)]
        for baseline, economy in pairs:
            baseline["cached_input_tokens"], baseline["reasoning_tokens"] = 80, 10
            economy["cached_input_tokens"], economy["reasoning_tokens"] = 60, 10
        result = benchmark.assess(pairs)
        self.assertEqual(result["median_token_reduction"], .25)
        self.assertIsNone(result["subscription_savings_percent"])

    def test_incomplete_real_task_cannot_be_hidden_behind_ten_successes(self):
        pairs = [self.pair(str(i)) for i in range(11)]
        pairs[-1][1]["coverage"]["helpers_included"] = False
        self.assertEqual(benchmark.assess(pairs)["status"], "insufficient-evidence")

    def test_slower_or_insufficient_reduction_does_not_pass(self):
        for changes in ({"elapsed_seconds": 11}, {"input_tokens": 95}):
            pairs = [self.pair(str(i)) for i in range(10)]
            for _, economy in pairs:
                economy.update(changes)
            self.assertEqual(benchmark.assess(pairs)["status"], "pilot-target-not-met")


if __name__ == "__main__":
    unittest.main()
