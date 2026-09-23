"""Exercise durable deduplication, resource limits, cancellation and real execution."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations/codex/subscription-savings"))
from context_economy.common import Store
from context_economy.job_queue import Queue, arguments


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src/a.py").write_text("def acquire():\n    return 1\n")
        self.store = Store(self.root, self.root / "state")
        self.addCleanup(self.store.close)
        self.queue = Queue(self.store)
        self.addCleanup(self.queue.close)

    def argv(self, term="acquire"):
        return ["search", term, "--source", "src"]

    def test_deduplication_real_worker_and_private_log(self):
        first = self.queue.submit(self.store, self.argv())
        second = self.queue.submit(self.store, self.argv())
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["deduplicated"])
        self.queue.run(self.queue.claim(self.root))
        row = self.queue.status(self.root, first["id"])[0]
        self.assertEqual(row["status"], "completed")
        log = Path(row["result"]["output"])
        self.assertIn("src/a.py", log.read_text())
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_stale_job_and_cancelled_job_do_not_run(self):
        first = self.queue.submit(self.store, self.argv())
        row = self.queue.claim(self.root)
        (self.root / "src/a.py").write_text("def acquire():\n    return 2\n")
        self.queue.run(row)
        self.assertEqual(self.queue.status(self.root, first["id"])[0]["status"], "stale")
        second = self.queue.submit(self.store, self.argv())
        self.queue.cancel(self.root, second["id"])
        self.assertIsNone(self.queue.claim(self.root))
        self.assertEqual(self.queue.status(self.root, second["id"])[0]["status"], "cancelled")

    def exercise_interruption(self, cancel):
        item = self.queue.submit(self.store, self.argv(), timeout=1)
        row = self.queue.claim(self.root)
        original = subprocess.Popen
        ready = self.root / "ready"
        script = ("import signal,time,pathlib,sys; "
                  "signal.signal(signal.SIGTERM,lambda *_:(print('cleanup',flush=True),sys.exit(0))); "
                  f"pathlib.Path({str(ready)!r}).touch(); time.sleep(30)")

        def launch(command, **kwargs):
            if command[0] == "git":
                return original(command, **kwargs)
            process = original([sys.executable, "-c", script], **kwargs)
            deadline = time.monotonic() + 3
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(ready.exists())
            if cancel:
                self.queue.cancel(self.root, item["id"])
            return process

        with mock.patch("context_economy.job_queue.subprocess.Popen", side_effect=launch):
            self.queue.run(row)
        result = self.queue.status(self.root, item["id"])[0]
        self.assertEqual(result["status"], "cancelled" if cancel else "failed")
        self.assertEqual(result["result"]["reason"], "cancelled" if cancel else "timeout")
        self.assertIn("cleanup", Path(result["result"]["output"]).read_text())

    def test_running_cancel_allows_cleanup(self):
        self.exercise_interruption(True)

    def test_timeout_is_failure_even_when_child_cleanup_exits_zero(self):
        self.exercise_interruption(False)

    def test_resource_limit_is_shared_between_projects(self):
        a = self.queue.submit(self.store, self.argv("one"))
        self.queue.submit(self.store, self.argv("two"))
        self.queue.submit(self.store, self.argv("three"))
        self.assertIsNotNone(self.queue.claim(self.root))
        self.assertIsNotNone(self.queue.claim(self.root))
        self.assertIsNone(self.queue.claim(self.root))
        other = self.root / "other"
        other.mkdir()
        (other / "b.py").write_text("def other(): pass\n")
        with Store(other, self.root / "state") as store:
            self.queue.submit(store, ["search", "other", "--source", "b.py"])
            self.assertIsNone(self.queue.claim(other))
            self.queue.finish(a["id"], "completed", {})
            self.assertIsNotNone(self.queue.claim(other))

    def test_dead_worker_requires_explicit_resubmission(self):
        item = self.queue.submit(self.store, self.argv())
        self.queue.claim(self.root)
        with self.queue.db:
            self.queue.db.execute("UPDATE jobs SET owner_token='not-this-process' WHERE id=?", (item["id"],))
        self.assertIsNone(self.queue.claim(self.root))
        self.assertEqual(self.queue.status(self.root, item["id"])[0]["status"], "interrupted")
        self.assertFalse(self.queue.submit(self.store, self.argv())["deduplicated"])

    def test_arbitrary_shell_and_queue_recursion_are_rejected(self):
        for argv in [["bash", "-c", "echo bad"], ["queue-worker"], ["search", "x", "--project", "/tmp"]]:
            with self.assertRaises(ValueError):
                arguments(argv)
        self.assertEqual(os.stat(self.queue.directory / "queue.sqlite3").st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
