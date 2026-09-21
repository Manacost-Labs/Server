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

from context_economy import advisor, pilot, remote  # noqa: E402
from context_economy.common import Store  # noqa: E402


class AdvisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self.task = self.root / "task.json"
        self.task.write_text(json.dumps({"goal": "Fix a bounded parser bug", "criteria": ["Tests pass"],
                                         "constraints": ["Preserve API"]}))
        (self.root / "AGENTS.md").write_text("PRIVATE LOCAL POLICY")
        self.store = Store(self.root, self.base / "state")
        self.ledger = remote.Ledger(self.base / "ledger")
        self.args = argparse.Namespace(task="task.json", category="implementation", risk="medium",
                                       selected_model="astra", preview_remote=False, allow_remote=True,
                                       daily_budget_usd=1, api_timeout=2)

    def tearDown(self):
        self.store.close()
        self.ledger.close()
        self.temp.cleanup()

    def response(self, model="terra", review="focused", confidence=0.9):
        return {"answers": {"model": {"choice": model, "confidence": confidence},
                            "review": {"choice": review, "confidence": confidence}}, "usage": {"cost": 0.00001}}

    def run_advice(self, response=None, side_effect=None):
        with mock.patch.object(remote, "Ledger", return_value=self.ledger), \
                mock.patch.object(self.ledger, "close"), \
                mock.patch.object(remote, "api_key", return_value="test-key"), \
                mock.patch.object(remote, "send", return_value=response or self.response(), side_effect=side_effect):
            return advisor.run(self.store, self.args)

    def outcome(self, advice, variant="advised", **kwargs):
        return dict({"advice_id": advice["id"], "case_id": "case-1", "variant": variant, "dataset": "real",
                     "model": "astra", "effort": "unknown", "speed": "standard",
                     "accepted": True, "checks_passed": True, "regressions": False,
                     "attempts": 2, "rework_cycles": 1, "evidence": "Focused parser tests passed"}, **kwargs)

    def test_preview_and_default_never_load_credentials_or_ledger(self):
        with mock.patch.object(remote, "Ledger", side_effect=AssertionError):
            self.args.preview_remote = True
            preview = advisor.run(self.store, self.args)
            self.assertNotIn("PRIVATE LOCAL POLICY", json.dumps(preview))
            self.assertNotIn(str(self.root), json.dumps(preview))
            self.assertNotIn("selected_model", preview["request"]["state"])
            self.args.preview_remote = False
            self.args.allow_remote = False
            result = advisor.run(self.store, self.args)
            self.assertEqual("astra", result["effective_model"])
            self.assertEqual(0, result["request_cost_usd"])

    def test_remote_advice_never_changes_selection(self):
        value = self.run_advice()
        self.assertEqual("terra", value["suggested_model"])
        self.assertEqual("astra", value["effective_model"])
        self.assertFalse(value["model_changed"])
        self.assertFalse(value["automatic_routing"])
        self.assertEqual(0.00001, value["request_cost_usd"])

    def test_senior_recommendation_and_review_floor(self):
        self.args.selected_model = "terra"
        self.args.risk = "high"
        value = self.run_advice(self.response("astra", "checks"))
        self.assertTrue(value["manual_senior_gate"])
        self.assertEqual("terra", value["effective_model"])
        self.assertEqual("independent", value["review"])

    def test_uncertain_or_low_confidence_retains_local_defaults(self):
        value = self.run_advice(self.response("luna", "checks", 0.4))
        self.assertIsNone(value["suggested_model"])
        self.assertEqual("focused", value["review"])

    def test_cache_does_not_double_charge(self):
        first = self.run_advice()
        second = self.run_advice(side_effect=AssertionError("No second HTTP call"))
        self.assertEqual(0.00001, first["request_cost_usd"])
        self.assertEqual(0, second["request_cost_usd"])
        self.assertEqual("cache", second["request_status"])
        self.assertEqual(1, self.ledger.summary()["requests"])

    def test_bad_answers_and_unknown_cost_fall_back(self):
        response = self.response()
        response["answers"]["model"]["confidence"] = True
        response["usage"] = None
        value = self.run_advice(response)
        self.assertEqual("fallback", value["status"])
        self.assertIsNone(value["request_cost_usd"])
        self.assertEqual("astra", value["effective_model"])
        self.assertEqual(0.003, self.ledger.summary()["unknown_reserved_usd"])

    def test_failure_and_task_change_never_persist_stale_advice(self):
        def fail(*args):
            self.task.write_text("{}")
            raise OSError("synthetic unavailable provider")
        with self.assertRaisesRegex(ValueError, "task changed"):
            self.run_advice(side_effect=fail)
        self.assertIsNone(self.store.db.execute("SELECT name FROM sqlite_master WHERE name='advice'").fetchone())

    def test_secret_oversize_and_extra_task_fields_rejected_before_network(self):
        original = json.loads(self.task.read_text())
        for value in (dict(original, goal="password=" + "x" * 20),
                      dict(original, goal="x" * 8001), dict(original, history="private")):
            self.task.write_text(json.dumps(value))
            with mock.patch.object(remote, "Ledger", side_effect=AssertionError), self.assertRaises(ValueError):
                advisor.run(self.store, self.args)

    def test_budget_validation_even_when_cached(self):
        self.run_advice()
        for budget in (0, -1, 2, float("nan")):
            self.args.daily_budget_usd = budget
            with self.assertRaises(ValueError):
                self.run_advice()

    def test_outcomes_preserve_unknowns_and_count_retries(self):
        advice = self.run_advice()
        pilot.record(self.store, self.outcome(advice))
        report = pilot.summary(self.store)
        group = report["groups"][0]
        self.assertEqual(0, group["matched_pairs"])
        self.assertIsNone(group["metrics"]["api_cost_usd"]["advised_total"])
        self.assertEqual(2, group["outcomes"]["advised"]["attempts"])
        self.assertFalse(report["automatic_routing"])
        with self.assertRaisesRegex(ValueError, "already recorded"):
            pilot.record(self.store, self.outcome(advice))

    def test_matched_comparison_exposes_quality_regression(self):
        advice = self.run_advice()
        pilot.record(self.store, self.outcome(advice, "baseline", input_tokens=100, output_tokens=20,
                                              cached_input_tokens=80, api_cost_usd=0.01))
        pilot.record(self.store, self.outcome(advice, accepted=False, model="terra", input_tokens=50,
                                              output_tokens=10, api_cost_usd=0.005))
        group = pilot.summary(self.store)["groups"][0]
        self.assertEqual(1, group["matched_pairs"])
        self.assertEqual(1, group["matched_quality_regressions"])
        self.assertEqual(100, group["metrics"]["input_tokens"]["baseline_total"])
        self.assertEqual(0, group["outcomes"]["advised"]["successful"])

    def test_changed_task_cannot_form_matched_pair(self):
        advice = self.run_advice()
        pilot.record(self.store, self.outcome(advice, "baseline"))
        task = json.loads(self.task.read_text())
        task["criteria"].append("Additional criterion")
        self.task.write_text(json.dumps(task))
        second = self.run_advice()
        pilot.record(self.store, self.outcome(second))
        self.assertEqual(0, pilot.summary(self.store)["groups"][0]["matched_pairs"])

    def test_synthetic_never_counts_in_real_pilot(self):
        advice = self.run_advice()
        pilot.record(self.store, self.outcome(advice, dataset="synthetic"))
        self.assertEqual([], pilot.summary(self.store)["groups"])
        self.assertEqual(1, pilot.summary(self.store, "synthetic")["groups"][0]["unique_cases"])

    def test_invalid_outcomes_and_cross_project_advice_rejected(self):
        advice = self.run_advice()
        for override in ({"advice_id": "missing"}, {"input_tokens": 1, "cached_input_tokens": 2},
                         {"api_cost_usd": float("nan")}, {"attempts": True}, {"accepted": "yes"},
                         {"quota_percent_saved": 60}):
            with self.assertRaises(ValueError):
                pilot.record(self.store, self.outcome(advice, **override))

    def test_cli_prints_advice_without_remote_by_default(self):
        value = subprocess.run([sys.executable, str(INTEGRATION / "context_economy.py"),
                                "--project", str(self.root), "--state-dir", str(self.base / "cli-state"),
                                "advise", "--task", "task.json", "--category", "implementation",
                                "--selected-model", "astra"], capture_output=True, text=True, check=True)
        self.assertEqual("astra", json.loads(value.stdout)["effective_model"])
        self.assertEqual("", value.stderr)


if __name__ == "__main__":
    unittest.main()
