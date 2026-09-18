import gzip
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

INTEGRATION = (
    Path(__file__).resolve().parents[1]
    / "integrations"
    / "codex"
    / "subscription-savings"
)
sys.path.insert(0, str(INTEGRATION))

import observation_pack as pack  # noqa: E402


class ObservationPackTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tempdir.name)
        self.config = pack.Config(
            base_dir=self.base,
            min_bytes=128,
            preview_head_chars=30,
            preview_tail_chars=20,
            ttl_seconds=60,
            max_storage_bytes=4096,
            max_metrics_bytes=4096,
            max_input_bytes=1024 * 1024,
        )

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def event(response, **overrides):
        value = {
            "hook_event_name": "PostToolUse",
            "session_id": "session/../../unsafe",
            "turn_id": "turn-1",
            "tool_name": "Bash",
            "tool_use_id": "tool-1",
            "tool_response": response,
        }
        value.update(overrides)
        return value

    def test_small_text_passes_through_without_archive(self):
        result = pack.process_event(self.event("short output"), self.config, now=1000)

        self.assertIsNone(result)
        self.assertEqual([], list((self.base / "records").glob("*.gz")))

    def test_default_threshold_captures_codex_truncated_shell_results(self):
        default = pack.Config(base_dir=self.base)

        self.assertLess(default.min_bytes, 8110)

    def test_large_text_is_archived_exactly_and_replaced_with_receipt(self):
        original = "HEAD\n" + ("middle line\n" * 300) + "TAIL\n"

        result = pack.process_event(self.event(original), self.config, now=1000)

        self.assertEqual("block", result["decision"])
        receipt = result["reason"]
        observation_id = pack.extract_observation_id(receipt)
        metadata = json.loads(
            (self.base / "records" / f"{observation_id}.json").read_text()
        )
        with gzip.open(
            self.base / "records" / metadata["data_file"], "rt", encoding="utf-8"
        ) as stream:
            restored = stream.read()
        self.assertEqual(original, restored)
        self.assertIn("HEAD", receipt)
        self.assertIn("TAIL", receipt)
        self.assertIn("recall", receipt)
        self.assertLess(len(receipt.encode()), len(original.encode()))

    def test_json_tool_response_round_trips_as_pretty_json(self):
        response = {"output": "x" * 300, "exit_code": 0}

        result = pack.process_event(self.event(response), self.config, now=1000)

        observation_id = pack.extract_observation_id(result["reason"])
        restored = pack.read_observation(self.base, observation_id)
        self.assertEqual(
            json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True), restored
        )

    def test_media_content_passes_through(self):
        response = {"content": [{"type": "image", "data": "x" * 1000}]}

        result = pack.process_event(self.event(response), self.config, now=1000)

        self.assertIsNone(result)

    def test_embedded_binary_resource_passes_through_without_archive(self):
        response = {
            "content": [
                {"type": "resource", "resource": {"blob": "A" * 1000}}
            ]
        }

        result = pack.process_event(self.event(response), self.config, now=1000)

        self.assertIsNone(result)
        self.assertFalse((self.base / "records").exists())

    def test_identifier_is_safe_and_does_not_include_session_value(self):
        result = pack.process_event(self.event("x" * 300), self.config, now=1000)

        observation_id = pack.extract_observation_id(result["reason"])
        self.assertRegex(observation_id, r"^[0-9a-f]{24}$")
        for path in self.base.rglob("*"):
            self.assertTrue(path.resolve().is_relative_to(self.base.resolve()))
            self.assertNotIn("unsafe", path.name)

    def test_recall_returns_requested_line_window(self):
        original = "".join(f"line-{number}\n" for number in range(1, 80))
        result = pack.process_event(self.event(original), self.config, now=1000)
        observation_id = pack.extract_observation_id(result["reason"])

        recalled = pack.recall_lines(
            self.base, observation_id, start_line=10, line_count=3
        )

        self.assertEqual("line-10\nline-11\nline-12\n", recalled)

    def test_recall_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            pack.recall_lines(self.base, "../../etc/passwd", 1, 10)

    def test_expired_records_are_removed(self):
        result = pack.process_event(self.event("x" * 300), self.config, now=1000)
        observation_id = pack.extract_observation_id(result["reason"])
        metadata_path = self.base / "records" / f"{observation_id}.json"
        data_path = self.base / "records" / f"{observation_id}.txt.gz"
        os.utime(metadata_path, (900, 900))
        os.utime(data_path, (900, 900))

        pack.cleanup(self.config, now=1000)

        self.assertFalse(metadata_path.exists())
        self.assertFalse(data_path.exists())

    def test_storage_cap_removes_oldest_records(self):
        roomy = pack.Config(**{**self.config.__dict__, "max_storage_bytes": 4096})
        first = pack.process_event(
            self.event("a" * 300, tool_use_id="one"), roomy, now=1000
        )
        first_id = pack.extract_observation_id(first["reason"])
        time.sleep(0.01)
        second = pack.process_event(
            self.event("b" * 300, tool_use_id="two"), roomy, now=1001
        )
        second_id = pack.extract_observation_id(second["reason"])
        records = self.base / "records"
        second_size = sum(
            (records / f"{second_id}{suffix}").stat().st_size
            for suffix in (".json", ".txt.gz")
        )
        one_record_cap = pack.Config(
            **{**self.config.__dict__, "max_storage_bytes": second_size}
        )

        pack.cleanup(one_record_cap, now=1001)

        self.assertFalse((self.base / "records" / f"{first_id}.json").exists())
        self.assertTrue((self.base / "records" / f"{second_id}.json").exists())

    def test_storage_cap_counts_orphaned_and_temporary_files(self):
        records = self.base / "records"
        records.mkdir(mode=0o700)
        orphan = records / "0123456789abcdef01234567.txt.gz"
        interrupted = records / ".observation-interrupted"
        orphan.write_bytes(b"o" * 80)
        interrupted.write_bytes(b"t" * 80)
        bounded = pack.Config(**{**self.config.__dict__, "max_storage_bytes": 50})

        pack.cleanup(bounded, now=1000)

        stored_bytes = sum(
            path.stat().st_size
            for path in records.iterdir()
            if path.is_file() and not path.is_symlink()
        )
        self.assertLessEqual(stored_bytes, 50)

    def test_record_that_cannot_fit_storage_cap_passes_through(self):
        tiny_cap = pack.Config(**{**self.config.__dict__, "max_storage_bytes": 1})

        result = pack.process_event(self.event("x" * 300), tiny_cap, now=1000)

        self.assertIsNone(result)
        records = self.base / "records"
        stored_bytes = sum(
            path.stat().st_size
            for path in records.iterdir()
            if path.is_file() and not path.is_symlink()
        )
        self.assertLessEqual(stored_bytes, 1)

    def test_metrics_record_estimated_context_savings(self):
        original = "z" * 1000

        result = pack.process_event(self.event(original), self.config, now=1000)

        metric = json.loads((self.base / "metrics.jsonl").read_text().splitlines()[-1])
        self.assertTrue(metric["archived"])
        self.assertEqual(len(original.encode()), metric["original_bytes"])
        self.assertEqual(len(result["reason"].encode()), metric["visible_bytes"])
        self.assertGreater(metric["estimated_saved_bytes"], 0)

    def test_archive_files_are_private(self):
        result = pack.process_event(self.event("q" * 300), self.config, now=1000)
        observation_id = pack.extract_observation_id(result["reason"])

        data_mode = (
            self.base / "records" / f"{observation_id}.txt.gz"
        ).stat().st_mode & 0o777
        metadata_mode = (
            self.base / "records" / f"{observation_id}.json"
        ).stat().st_mode & 0o777
        self.assertEqual(0o600, data_mode)
        self.assertEqual(0o600, metadata_mode)

    def test_metrics_file_is_bounded(self):
        bounded = pack.Config(**{**self.config.__dict__, "max_metrics_bytes": 500})

        for number in range(20):
            pack.process_event(
                self.event(f"small-{number}"), bounded, now=1000 + number
            )

        self.assertLessEqual((self.base / "metrics.jsonl").stat().st_size, 500)

    def test_invalid_environment_is_fail_open_for_hook_invocation(self):
        environment = os.environ.copy()
        environment["CODEX_OBSERVATION_PACK_MIN_BYTES"] = "not-a-number"

        completed = subprocess.run(
            [sys.executable, str(INTEGRATION / "observation_pack.py")],
            input=b"{}",
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertEqual(0, completed.returncode)
        self.assertEqual(b"", completed.stdout)
        self.assertEqual(b"", completed.stderr)

    def test_input_read_failure_is_fail_open(self):
        class BrokenInput:
            class Buffer:
                @staticmethod
                def read(_limit):
                    raise OSError("synthetic read failure")

            buffer = Buffer()

        with mock.patch.object(pack.sys, "stdin", BrokenInput()):
            self.assertEqual(0, pack._run_hook(self.config))


if __name__ == "__main__":
    unittest.main()
