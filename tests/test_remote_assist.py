import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integrations/codex/subscription-savings"
sys.path.insert(0, str(INTEGRATION))

from context_economy import assist, remote  # noqa: E402
from context_economy.common import Store, encode  # noqa: E402


class RemoteAssistTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "project"
        self.root.mkdir()
        (self.root / "AGENTS.md").write_text("MANDATORY LOCAL INSTRUCTIONS\n")
        (self.root / "docs.txt").write_text("The API handles requests.\n" + "Additional reference information.\n" * 180)
        (self.root / "task.json").write_text(json.dumps({"goal": "Explain the API", "criteria": ["Cite sources"],
                                                       "constraints": ["Do not modify code"]}))
        self.store = Store(self.root, self.base / "state")
        self.ledger = remote.Ledger(self.base / "ledger")
        self.args = argparse.Namespace(task="task.json", source=["docs.txt"], required=[], purpose="context",
                                       provider="gemma", mode="shadow", preview_remote=False, allow_remote=True,
                                       daily_budget_usd=1.0, api_timeout=2, budget=12000)

    def tearDown(self):
        self.store.close()
        self.ledger.close()
        self.temp.cleanup()

    def response(self):
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
            "items": [{"source_id": "s0", "quote": "The API handles requests.", "note": "API overview"}],
            "uncertainties": []})}}], "usage": {"cost": 0.001}}

    def run_assist(self, response=None):
        with mock.patch.object(remote, "Ledger", return_value=self.ledger), \
                mock.patch.object(self.ledger, "close"), \
                mock.patch.object(remote, "api_key", return_value="synthetic-test-key"), \
                mock.patch.object(remote, "send", return_value=response or self.response()):
            return assist.run(self.store, self.args)

    def test_preview_never_uses_credentials_and_excludes_pinned_sources(self):
        self.args.source.append("AGENTS.md")
        self.args.preview_remote = True
        self.args.provider = "cascade"
        with mock.patch.object(remote, "api_key", side_effect=AssertionError):
            value = assist.run(self.store, self.args)
        text = encode(value)
        self.assertNotIn("MANDATORY LOCAL", text)
        self.assertIn("/api/alpha/decisions", text)
        self.assertIn("typesafe/jev-1.13", text)
        self.assertEqual(0.09, value["requests"]["gemma"]["provider"]["max_price"]["prompt"])

    def test_local_default_does_not_initialize_remote_ledger(self):
        self.args.allow_remote = False
        with mock.patch.object(remote, "Ledger", side_effect=AssertionError):
            value = assist.run(self.store, self.args)
        self.assertEqual("local", value["status"])
        self.assertEqual("MANDATORY LOCAL INSTRUCTIONS\n", value["packet"]["required_sources"][0]["text"])

    def test_shadow_keeps_original_and_active_uses_smaller_cited_packet(self):
        value = self.run_assist()
        self.assertEqual("shadow", value["status"])
        self.assertIn("Additional reference information", value["packet"]["context"][0]["text"])
        self.args.mode = "active"
        active = self.run_assist()
        self.assertEqual("active", active["status"])
        self.assertEqual(value["packet"]["required_sources"], active["packet"]["required_sources"])
        self.assertEqual("The API handles requests.", active["packet"]["context"][0]["quote"])
        self.assertTrue(active["draft"])
        self.assertEqual("cache", active["usage"][0]["status"])
        self.assertEqual(1, self.ledger.summary()["requests"])

    def test_fabricated_or_omitted_evidence_falls_back(self):
        for items in ([{"source_id": "s0", "quote": "INVENTED", "note": "wrong"}], []):
            response = self.response()
            response["choices"][0]["message"]["content"] = json.dumps({"items": items, "uncertainties": []})
            result = self.run_assist(response)
            self.assertEqual("fallback", result["status"])
            self.assertIn("text", result["packet"]["context"][0])

    def test_truncated_generation_is_rejected(self):
        response = self.response()
        response["choices"][0]["finish_reason"] = "length"
        self.assertEqual("fallback", self.run_assist(response)["status"])

    def test_changed_pinned_source_emits_no_stale_packet(self):
        def call(*_):
            (self.root / "AGENTS.md").write_text("New mandatory instruction")
            return self.response()
        with mock.patch.object(remote, "Ledger", return_value=self.ledger), \
                mock.patch.object(self.ledger, "close"), \
                mock.patch.object(remote, "api_key", return_value="test"), \
                mock.patch.object(remote, "send", side_effect=call), self.assertRaises(assist.StaleSource):
            assist.run(self.store, self.args)

    def test_budget_shared_between_connections_and_unknown_cost_retained(self):
        other = remote.Ledger(self.base / "ledger")
        try:
            identifier = self.ledger.reserve("jev", "one", 0.003)
            self.ledger.finish(identifier, {})
            with self.assertRaises(ValueError):
                other.reserve("jev", "two", 0.003)
            self.assertEqual(0.003, other.summary()["unknown_reserved_usd"])
        finally:
            other.close()

    def test_deleted_source_after_failed_http_cannot_use_stale_fallback(self):
        def fail(*_):
            (self.root / "docs.txt").unlink()
            raise OSError("timeout")
        with mock.patch.object(remote, "Ledger", return_value=self.ledger), \
                mock.patch.object(self.ledger, "close"), \
                mock.patch.object(remote, "api_key", return_value="test"), \
                mock.patch.object(remote, "send", side_effect=fail), self.assertRaises(assist.StaleSource):
            assist.run(self.store, self.args)

    def test_failed_request_is_reserved_and_not_cached(self):
        with mock.patch.object(remote, "api_key", return_value="test"), \
                mock.patch.object(remote, "send", side_effect=OSError("private provider error")):
            with self.assertRaisesRegex(ValueError, "Remote request failed"):
                remote.request(self.store, self.ledger, "gemma", {}, 1, lambda x: x)
        self.assertEqual(0.025, self.ledger.summary()["unknown_reserved_usd"])
        self.assertEqual(0, self.store.db.execute("SELECT COUNT(*) FROM assistant_cache").fetchone()[0])

    def test_missing_key_reserves_nothing(self):
        with mock.patch.object(remote, "api_key", side_effect=ValueError("missing")), self.assertRaises(ValueError):
            remote.request(self.store, self.ledger, "jev", {}, 1, lambda x: x)
        self.assertEqual(0, self.ledger.summary()["requests"])

    def test_null_usage_retains_reservation(self):
        identifier = self.ledger.reserve("jev", "null-usage", 1)
        self.ledger.finish(identifier, {"usage": None})
        self.assertEqual(0.003, self.ledger.summary()["unknown_reserved_usd"])

    def test_budget_invalid_or_too_small(self):
        for amount in (0, -1, float("nan"), float("inf"), 2, 0.0001):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.ledger.reserve("gemma", "test", amount)

    def test_source_and_state_budget_guards(self):
        (self.root / ".env").write_text("private")
        for spec in (".env", "../outside"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                assist.prepare(self.root, "task.json", [spec], [], "context", 12000)
        (self.root / "docs.txt").write_text("x" * 25000)
        with self.assertRaisesRegex(ValueError, "24 KB"):
            assist.prepare(self.root, "task.json", ["docs.txt"], [], "context", 12000)

    def test_private_credential_file_and_symlink_rejection(self):
        config = self.base / ".config/codex-context-economy"
        config.mkdir(parents=True)
        key = config / "remote.env"
        key.write_text("OPENROUTER_API_KEY='synthetic-test'\n")
        with mock.patch.object(remote.Path, "home", return_value=self.base), mock.patch.dict(os.environ, {}, clear=True):
            key.chmod(0o644)
            with self.assertRaises(ValueError):
                remote.api_key()
            key.chmod(0o600)
            self.assertEqual("synthetic-test", remote.api_key())
            key.rename(config / "original")
            key.symlink_to(config / "original")
            with self.assertRaises(OSError):
                remote.api_key()

    def test_cli_stdout_only_packet_report_private(self):
        command = [sys.executable, str(INTEGRATION / "context_economy.py"), "--project", str(self.root),
                   "--state-dir", str(self.base / "cli-state"), "assist", "--task", "task.json", "--source", "docs.txt"]
        completed = subprocess.run(command, capture_output=True, text=True, check=True)
        packet = json.loads(completed.stdout)
        metadata = json.loads(completed.stderr)
        self.assertIn("required_sources", packet)
        self.assertNotIn("candidate_packet", packet)
        self.assertEqual(0o600, Path(metadata["report"]).stat().st_mode & 0o777)

    def test_each_source_must_be_cited(self):
        candidates = {"s0": {"text": "The API handles requests."}, "s1": {"text": "Another source"}}
        with self.assertRaisesRegex(ValueError, "omitted"):
            assist.validate_gemma(copy.deepcopy(self.response()), candidates)


if __name__ == "__main__":
    unittest.main()
