"""Offline process E2E, plus installed-CLI configuration validation without auth."""
import copy
import json
import os
import shlex
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
import benchmark  # noqa: E402
import codex_setup as setup  # noqa: E402
import token_budget  # noqa: E402

FAKE = '''#!/usr/bin/env python3
import json,os,pathlib,sys,tomllib
a=sys.argv[1:];home=pathlib.Path(os.environ['CODEX_HOME'])
if a==['--version']: print('codex-cli 0.153.0')
elif a==['--help']: print('-p <CONFIG_PROFILE_V2> $CODEX_HOME/<name>.config.toml')
elif 'app-server' in a: pass
elif 'list' in a:
 b=tomllib.loads((home/'config.toml').read_text())['mcp_servers']
 p=tomllib.loads((home/(a[a.index('-p')+1]+'.config.toml')).read_text())
 for n,v in p['mcp_servers'].items(): b.setdefault(n,{}).update(v)
 print(json.dumps([dict(name=n,enabled=v.get('enabled',True)) for n,v in b.items()]))
elif 'exec' in a:
 pathlib.Path(a[a.index('--output-last-message')+1]).write_text('Verified synthetic summary')
 print(json.dumps({'type':'turn.completed','usage':{'input_tokens':120,'cached_input_tokens':20,'output_tokens':30}}))
else: print(json.dumps({'argv':a}))
'''


class SetupE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "codex-home"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.fake = self.bin / "codex"
        self.fake.write_text(FAKE)
        self.fake.chmod(0o700)
        self.env = {**os.environ, "CODEX_HOME": str(self.home), "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                    "CODEX_OBSERVATION_PACK_DIR": str(self.root / "observations")}

    def run_process(self, argv, payload=None, env=None):
        return subprocess.run([str(a) for a in argv], input=payload, capture_output=True, text=True,
                              cwd=self.root, env=env or self.env, timeout=30)

    def installer(self, mode):
        return self.run_process([sys.executable, INTEGRATION / "codex_setup.py", mode])

    def install(self):
        result = self.installer("--install")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dry_run_no_mutation_install_backup_repeat_verify(self):
        result = self.installer("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.home.exists())
        self.install()
        first = {p.name: p.read_bytes() for p in self.home.glob("*.toml")}
        self.assertTrue(list(self.home.glob("economy-backup-*/restore.json")))
        result = self.installer("--install")
        self.assertEqual(json.loads(result.stdout)["status"], "unchanged")
        self.assertEqual(first, {p.name: p.read_bytes() for p in self.home.glob("*.toml")})
        self.assertEqual(self.installer("--verify").returncode, 0)

    def test_refuses_unknown_and_modified_config(self):
        self.home.mkdir()
        path = self.home / "config.toml"
        path.write_text('model="custom"\n')
        self.assertNotEqual(self.installer("--install").returncode, 0)
        self.assertEqual(path.read_text(), 'model="custom"\n')
        path.unlink()
        self.install()
        path.write_text(path.read_text() + "# operator change\n")
        self.assertNotEqual(self.installer("--install").returncode, 0)

    def test_all_profiles_mcp_allowlists_and_minimal_launch(self):
        self.install()
        for name, active in setup.PROFILES.items():
            self.assertEqual({n for n, v in setup.effective(self.home, name).items() if v["enabled"]}, set(active))
        result = self.run_process(["bash", INTEGRATION / "bin/codex-context", "minimal"])
        self.assertEqual(json.loads(result.stdout)["argv"], ["-p", "minimal"])
        (self.home / "minimal.config.toml").unlink()
        result = self.run_process(["bash", INTEGRATION / "bin/codex-context", "minimal"])
        self.assertIn("Missing profile", result.stderr)

    def test_installer_rollback_and_user_state_preserved(self):
        self.install()
        auth = self.home / "operator-note.txt"
        auth.write_text("unrelated user state")
        previous = setup.ownership(self.home)
        original = {n: (self.home / n).read_bytes() for n in [*previous["files"], setup.MANIFEST]}
        changed = setup.rendered()
        changed["config.toml"] += b"\n# managed upgrade\n"
        write = setup.atomic
        failed = False

        def failing_write(path, data):
            nonlocal failed
            if path == self.home / "code.config.toml" and not failed:
                failed = True
                raise OSError("synthetic disk failure")
            write(path, data)

        with mock.patch.object(setup, "atomic", side_effect=failing_write):
            with self.assertRaises(OSError):
                setup.install(self.home, changed, previous)
        self.assertEqual(original, {n: (self.home / n).read_bytes() for n in original})
        self.assertEqual(auth.read_text(), "unrelated user state")

    def test_missing_cli_and_symlink_home_refused(self):
        with mock.patch.object(setup.shutil, "which", side_effect=lambda name: None if name == "codex" else "/bin/true"):
            with self.assertRaisesRegex(ValueError, "codex is missing"):
                setup.cli_check()
        target = self.root / "target"
        target.mkdir()
        self.home.symlink_to(target)
        self.assertNotEqual(self.installer("--install").returncode, 0)
        self.assertEqual(list(target.iterdir()), [])

    def test_unexpected_mcp_override_and_incompatible_cli(self):
        self.install()
        with (self.home / "config.toml").open("a") as stream:
            stream.write('\n[mcp_servers.surprise]\ncommand="true"\nenabled=true\n')
        result = self.run_process(["bash", INTEGRATION / "bin/codex-context", "minimal"])
        self.assertIn("Incompatible minimal MCP set", result.stderr)
        self.fake.write_text(FAKE.replace("codex-cli 0.153.0", "codex-cli 0.152.0"))
        self.assertIn("Unsupported Codex version", self.installer("--dry-run").stderr)

    def test_typeui_plugin_preserved_without_enabling_mcp(self):
        self.install()
        profile = self.home / "typeui.config.toml"
        original = profile.read_text()
        plugin = '\n[plugins."typeui@bergside"]\nenabled = true\n'
        profile.write_text(original + plugin)
        result = self.run_process(["bash", INTEGRATION / "bin/codex-context", "typeui"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["argv"], ["-p", "typeui"])
        self.assertEqual({n for n, v in setup.effective(self.home, "typeui").items() if v["enabled"]}, set())
        for invalid in [plugin.replace("true", '"yes"'), plugin + 'command = "unexpected"\n',
                        '\n[model_providers.custom]\nname = "unexpected"\n']:
            profile.write_text(original + invalid)
            result = self.run_process(["bash", INTEGRATION / "bin/codex-context", "typeui"])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Incompatible", result.stderr)

    def test_model_manual_gate_and_missing_dependency(self):
        self.install()
        result = self.run_process(["bash", INTEGRATION / "bin/codex-run", "astra"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires a specific --reason", result.stderr)
        result = self.run_process(["bash", INTEGRATION / "bin/codex-run", "terra", "minimal", "--model", "gpt-6-astra"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("model overrides bypass", result.stderr)
        package = self.root / "handoff.txt"
        package.write_text("Named hard decision; synthetic fixture, no API call.")
        result = self.run_process(["bash", INTEGRATION / "bin/codex-run", "astra", "--reason",
                                   "Synthetic named decision", "--package", package, "minimal"])
        self.assertEqual(json.loads(result.stdout)["argv"], ["-p", "minimal", "-m", "gpt-6-astra"])
        result = self.run_process(["bash", INTEGRATION / "bin/codex-run", "terra", "minimal"])
        self.assertEqual(json.loads(result.stdout)["argv"], ["-p", "minimal", "-m", "gpt-5.6-terra"])
        p = self.home / "config.toml"
        p.write_text(p.read_text().replace('command = "codegraph"', 'command = "definitely-missing-economy-tool"'))
        result = self.run_process(["bash", INTEGRATION / "bin/codex-context", "code"])
        self.assertIn("Missing profile tools", result.stderr)

    def test_post_tool_hook_archives_and_recalls_exact_unicode(self):
        import tomllib
        self.install()
        config = tomllib.loads((self.home / "config.toml").read_text())
        command = config["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
        original = ("Русский код JSON {\"key\":123} " * 80 + "\n") * 8
        result = self.run_process(shlex.split(command), json.dumps({"hook_event_name": "PostToolUse",
                                 "session_id": "synthetic", "tool_name": "Bash", "tool_response": original}))
        output = json.loads(result.stdout)
        import re
        identifier = re.search(r"ObservationPack id=([a-f0-9]+)", output["reason"])[1]
        result = self.run_process([sys.executable, INTEGRATION / "observation_pack.py", "recall", identifier,
                                   "--start-line", "1", "--lines", "20"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, original)

    def transcript(self, counter, cached=0, padding=70000):
        path = self.home / "sessions/test.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {
            "input_tokens": counter, "cached_input_tokens": cached, "output_tokens": 100}}}}
        path.write_text(json.dumps({"padding": "x" * padding}) + "\n" + json.dumps(row) + "\n")
        return json.dumps({"transcript_path": str(path)})

    def plugin(self):
        path = self.home / "plugins/compact-plus/hooks/precompact-state-summary.sh"
        path.parent.mkdir(parents=True)
        path.write_text('printf "summarize" | sh -c "$COMPACT_PLUS_PRIMARY_BACKEND"\n')

    def compaction(self, payload):
        return self.run_process(["bash", INTEGRATION / "bin/compact-plus-hook", "precompact-state-summary.sh"], payload)

    def test_compaction_short_cheap_expensive_cost_and_repeat(self):
        self.plugin()
        self.assertEqual(self.compaction(self.transcript(100000, padding=30)).stdout, "")
        self.assertEqual(self.compaction(self.transcript(100000, cached=99000)).stdout, "")
        payload = self.transcript(100000)
        result = self.compaction(payload)
        self.assertEqual(result.stdout, "Verified synthetic summary", result.stderr)
        self.assertEqual(self.compaction(payload).stdout, "")
        rows = [json.loads(s) for s in (self.home / "economy-metrics/compaction.jsonl").read_text().splitlines()]
        usage = next(r for r in rows if r["status"] == "completed")
        self.assertEqual(usage["actual_codex_tokens"]["input_tokens"], 120)
        self.assertIsNone(usage["actual_codex_tokens"]["reasoning_output_tokens"])
        self.assertEqual(sum(r["model_launches"] for r in rows), 1)

    def test_compaction_missing_plugin_and_bad_input_fail_open(self):
        self.assertEqual(self.compaction("{}").returncode, 0)
        self.plugin()
        self.assertEqual(self.compaction("not JSON").returncode, 0)
        self.assertEqual(self.compaction("[]").returncode, 0)

    def test_compaction_counter_reset_does_not_launch(self):
        self.plugin()
        payload = self.transcript(100000)
        path = self.home / "sessions/test.jsonl"
        row = json.loads(path.read_text().splitlines()[-1])
        row["payload"]["info"]["total_token_usage"]["input_tokens"] = 90000
        with path.open("a") as stream:
            stream.write(json.dumps(row) + "\n")
        self.assertEqual(self.compaction(payload).stdout, "")

    def test_budget_unicode_code_json_and_missing_tokenizer(self):
        for text in ["Русский текст 🦔", "def f(x):\n return x + 1\n", json.dumps({"ключ": [1, 2, 3]})]:
            for model in ["gpt-6-astra", "gpt-5.6-terra", "unknown"]:
                result = token_budget.estimate_text(text, model)
                self.assertGreaterEqual(result["estimated_tokens"], len(text.encode()))
                self.assertIsNone(result["actual_codex_tokens"])
        with mock.patch.dict(sys.modules, {"tiktoken": None}):
            self.assertEqual(token_budget.estimate_text("abc", "gpt-4o")["method"], "utf8-bytes-upper-estimate")
        p = self.root / "input.txt"
        p.write_text("Русский " * 100)
        result = self.run_process(["bash", INTEGRATION / "bin/context-budget", "--model", "gpt-6-astra", "--limit", "10", p])
        self.assertEqual(result.returncode, 3)
        self.assertTrue(json.loads(result.stdout)["exceeded"])

    def test_compatible_tokenizer_counts_with_margin(self):
        tokenizer = mock.Mock()
        tokenizer.get_encoding.return_value.encode.return_value = [1, 2, 3]
        with mock.patch.dict(sys.modules, {"tiktoken": tokenizer}):
            result = token_budget.estimate_text("source", "gpt-4o")
        self.assertEqual(result["tokenizer_tokens"], 3)
        self.assertEqual(result["estimated_tokens"], 4)
        tokenizer.get_encoding.assert_called_once_with("o200k_base")


class RealCLIConfig(unittest.TestCase):
    @unittest.skipUnless(shutil.which("codex"), "installed Codex unavailable; offline contract tests still run")
    def test_installed_cli_all_profiles_and_strict_config(self):
        setup.cli_check()
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            for name, data in setup.rendered().items():
                (home / name).write_bytes(data)
            for profile in setup.PROFILES:
                setup.validate_runtime(home, profile)
            with (home / "config.toml").open("a") as stream:
                stream.write('\n[not_supported_economy_setting]\nx=1\n')
            with self.assertRaises(subprocess.CalledProcessError):
                setup.validate_runtime(home, "minimal")


class BenchmarkTests(unittest.TestCase):
    def pair(self):
        row = json.loads((INTEGRATION / "benchmark/baseline.template.json").read_text())
        row.update(dataset="synthetic", source_commit="a" * 40, model="test-model", reasoning_effort="medium", speed="standard",
                   measurement="observed", evidence="synthetic fixture only")
        row.update({k: 1 for k in benchmark.METRICS})
        row["tests"] = dict(passed=True, command="synthetic check", evidence="fixture")
        row["quality"] = dict(accepted=True, criteria="fixture criteria", rework_notes="none")
        other = copy.deepcopy(row)
        other["variant"] = "economy"
        return row, other

    def test_comparable_pair_and_unknown_fields(self):
        a, b = self.pair()
        result = benchmark.compare(a, b)
        self.assertEqual(result["status"], "matched-observations")
        self.assertIsNone(result["subscription_savings_percent"])
        b["elapsed_seconds"] = None
        self.assertEqual(benchmark.compare(a, b)["status"], "incomplete")

    def test_unmatched_commit_settings_quality_and_invalid_counts(self):
        for key in ["source_commit", "model", "reasoning_effort", "speed", "task"]:
            a, b = self.pair()
            b[key] = "b" * 40 if key == "source_commit" else "different"
            with self.assertRaises(ValueError):
                benchmark.compare(a, b)
        for key, value in [("cached_input_tokens", 2), ("model_launches", True), ("elapsed_seconds", float("nan"))]:
            a, b = self.pair()
            b[key] = value
            with self.assertRaises(ValueError):
                benchmark.compare(a, b)
        a, b = self.pair()
        b["quality"]["accepted"] = False
        self.assertFalse(benchmark.compare(a, b)["quality_preserved"])


if __name__ == "__main__":
    unittest.main()
