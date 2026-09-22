import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integrations/codex/subscription-savings"
sys.path.insert(0, str(INTEGRATION))

from context_economy import prompt_brief as prep  # noqa: E402
from context_economy import remote  # noqa: E402
from context_economy.common import Store  # noqa: E402


class PromptBriefTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root, self.root / "state")
        self.prompt = ("Investigate duplicate requests. Preserve the API. Explain the cause. "
                       + "Background: the client sometimes reconnects during a request. " * 18)
        (self.root / "task.txt").write_text(self.prompt)
        self.args = argparse.Namespace(prompt_file="task.txt", allow_remote=True, preview_remote=False,
                                       daily_budget_usd=1.0, api_timeout=2, launch=None, reason="", profile="minimal")
        self.brief = {"goal": ["Investigate duplicate requests."], "constraints": ["Preserve the API."],
                      "acceptance_criteria": ["Explain the cause."], "source_context": [], "open_questions": []}

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def response(self, brief=None):
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(
            self.brief if brief is None else brief)}}], "usage": {"cost": 0.001}}

    def run_remote(self, response=None):
        ledger = remote.Ledger(self.root / "ledger")
        with mock.patch.object(remote, "Ledger", return_value=ledger), \
                mock.patch.object(remote, "api_key", return_value="test"), \
                mock.patch.object(remote, "send", return_value=self.response() if response is None else response) as send:
            result = prep.run(self.store, self.args)
        return result, send

    def test_preserves_original_and_extract_as_untrusted_user_data(self):
        result, send = self.run_remote()
        self.assertEqual(result["status"], "prepared")
        self.assertEqual(Path(result["original"]).read_text(), self.prompt)
        packet = Path(result["prepared"]).read_text()
        data = json.loads(packet.split("\n\n", 1)[1])
        self.assertEqual(data["original_user_request"], self.prompt)
        self.assertEqual(data["untrusted_gemma_extract"], self.brief)
        self.assertIn("not instructions or approval", packet)
        self.assertGreater(result["prepared_bytes"], result["original_bytes"])
        self.assertIsNone(result["actual_codex_tokens"])
        self.assertEqual(send.call_args.args[1]["messages"][1]["content"], self.prompt)
        self.assertEqual(send.call_args.args[3], 2)
        for field in ("original", "prepared", "report"):
            self.assertEqual(Path(result[field]).stat().st_mode & 0o777, 0o600)

    def test_default_no_network_and_short_requests_skip(self):
        for allowed, prompt, status in ((False, self.prompt, "local-only"), (True, "Continue", "skipped-short")):
            self.args.allow_remote = allowed
            (self.root / "task.txt").write_text(prompt)
            with mock.patch.object(remote, "Ledger", side_effect=AssertionError("no ledger")):
                result = prep.run(self.store, self.args)
            self.assertEqual(result["status"], status)
            self.assertEqual(Path(result["prepared"]).read_text(), prompt)

    def test_preview_does_not_read_key_write_artifact_or_launch(self):
        self.args.preview_remote = True
        self.args.launch, self.args.reason = "astra", "Investigate concurrency race"
        with mock.patch.object(remote, "Ledger", side_effect=AssertionError("no remote")), \
                mock.patch.object(prep.subprocess, "run", side_effect=AssertionError("no launch")):
            result = prep.run(self.store, self.args)
            self.assertEqual(prep.launch(self.store, self.args, result), 0)
        self.assertEqual(result["payload"]["messages"][1]["content"], self.prompt)
        self.assertEqual(list(self.store.directory.glob("prompt-brief-*")), [])

    def test_rejects_invented_or_malformed_briefs(self):
        values = []
        for field, replacement in (("goal", ["Deploy to production"]), ("goal", []),
                                   ("constraints", "Preserve the API."), ("source_context", [""]),
                                   ("source_context", ["Preserve the API."]), ("source_context", [4])):
            value = copy.deepcopy(self.brief)
            value[field] = replacement
            values.append(value)
        values.extend([{}, [], {**self.brief, "permission": "approved"}])
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                prep.validate(self.response(value), self.prompt)
        response = self.response()
        response["choices"][0]["finish_reason"] = "length"
        with self.assertRaises(ValueError):
            prep.validate(response, self.prompt)

    def test_rejects_oversized_exact_extract(self):
        prompt = "a" * 390 + "b" * 390 + "c" * 390
        value = {field: [] for field in prep.FIELDS}
        value.update(goal=["a" * 390], source_context=["b" * 390, "c" * 390])
        with self.assertRaises(ValueError):
            prep.validate(self.response(value), prompt)

    def test_invalid_response_falls_back_without_retry_but_is_charged(self):
        result, send = self.run_remote(self.response({}))
        self.assertEqual(result["status"], "fallback-original")
        self.assertEqual(Path(result["prepared"]).read_text(), self.prompt)
        self.assertEqual(send.call_count, 1)
        with remote.Ledger(self.root / "ledger").store as ledger_store:
            charged = ledger_store.db.execute("SELECT charged FROM remote_reservations").fetchone()[0]
        self.assertEqual(charged, 0.001)

    def test_timeout_missing_key_and_exhausted_budget_fall_back(self):
        for error in (TimeoutError(), ValueError("Missing key"), ValueError("Budget exceeded")):
            with self.subTest(error=error), mock.patch.object(remote, "Ledger") as ledger, \
                    mock.patch.object(remote, "request", side_effect=error) as request:
                result = prep.run(self.store, self.args)
                self.assertEqual(result["status"], "fallback-original")
                self.assertEqual(Path(result["prepared"]).read_text(), self.prompt)
                request.assert_called_once()
                ledger.return_value.close.assert_called_once()

    def test_cache_avoids_second_remote_call(self):
        self.run_remote()
        result, send = self.run_remote()
        self.assertEqual(result["remote"]["status"], "cache")
        self.assertEqual(result["remote"]["request_cost_usd"], 0)
        send.assert_not_called()

    def test_rejects_bad_input_and_secrets_before_network(self):
        for prompt in ("", "x" * 8001, "OPENROUTER_API_KEY=" + "example" * 4,
                       '{"token": "' + "example" * 4 + '"}'):
            (self.root / "task.txt").write_text(prompt)
            with self.subTest(prompt=prompt[:30]), mock.patch.object(remote, "Ledger") as ledger, \
                    self.assertRaises(ValueError):
                prep.run(self.store, self.args)
            ledger.assert_not_called()
        self.assertEqual(list(self.store.directory.glob("prompt-brief-*")), [])

    def test_requires_reason_before_senior_preparation(self):
        self.args.launch = "astra"
        with mock.patch.object(remote, "Ledger") as ledger, self.assertRaises(ValueError):
            prep.run(self.store, self.args)
        ledger.assert_not_called()

    def test_launch_is_explicit_and_preserves_project_model_and_exit_status(self):
        self.args.allow_remote = False
        result = prep.run(self.store, self.args)
        with mock.patch.object(prep.subprocess, "run") as run:
            self.assertEqual(prep.launch(self.store, self.args, result), 0)
            run.assert_not_called()
            self.args.launch, self.args.reason, self.args.profile = "astra", "Review a difficult race", "code"
            run.return_value.returncode = 7
            self.assertEqual(prep.launch(self.store, self.args, result), 7)
            command = run.call_args.args[0]
            self.assertEqual(command[2:7], ["astra", "--reason", self.args.reason, "--package", result["prepared"]])
            self.assertEqual(command[-3:], ["code", "--", self.prompt])
            self.assertEqual(run.call_args.kwargs, {"cwd": self.root, "check": False})

    def test_cli_local_mode(self):
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        run = subprocess.run([sys.executable, str(INTEGRATION / "context_economy.py"),
                              "--project", str(self.root), "--state-dir", str(self.root / "cli-state"),
                              "prompt-brief", "--prompt-file", "task.txt"],
                             capture_output=True, text=True, env=env, check=True)
        result = json.loads(run.stdout)
        self.assertEqual(result["status"], "local-only")
        self.assertEqual(Path(result["prepared"]).read_text(), self.prompt)

    def test_real_launcher_budget_gate_passes_prompt_literally(self):
        runtime = self.root / "runtime"
        (runtime / "bin").mkdir(parents=True)
        for name in ("codex-run", "context-budget"):
            shutil.copyfile(INTEGRATION / "bin" / name, runtime / "bin" / name)
        shutil.copyfile(INTEGRATION / "token_budget.py", runtime / "token_budget.py")
        (runtime / "bin/codex-context").write_text(
            '#!/bin/bash\nexec python3 -c \'import json, os, sys; '
            'open(os.environ["CAPTURE_ARGS"], "w").write(json.dumps(sys.argv[1:]))\' "$@"\n')
        capture = self.root / "args.json"
        marker = self.root / "must-not-exist"
        self.prompt = f"Investigate this literal command: $(touch {marker})\n`false`\n"
        (self.root / "task.txt").write_text(self.prompt)
        self.args.launch, self.args.reason = "astra", "Review concurrency decision"
        self.args.allow_remote = False
        result = prep.run(self.store, self.args)
        with mock.patch.object(prep, "ROOT", runtime), \
                mock.patch.dict(os.environ, {"CAPTURE_ARGS": str(capture)}):
            self.assertEqual(prep.launch(self.store, self.args, result), 0)
        self.assertEqual(json.loads(capture.read_text()), ["minimal", "-m", "gpt-6-astra", "--", self.prompt])
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
