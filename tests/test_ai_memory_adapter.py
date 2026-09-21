import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

INTEGRATION = Path(__file__).resolve().parents[1] / "integrations/codex/subscription-savings"
sys.path.insert(0, str(INTEGRATION))

from context_economy import ai_memory, memory  # noqa: E402
from context_economy.common import Store  # noqa: E402
from memory_hook import hint  # noqa: E402


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        (self.root / "code.txt").write_text("verified source\n")
        token = self.base / "token"
        token.write_text("synthetic-local-test-token")
        self.project = {"id": "one", "root": str(self.root), "git_common_dir": str(self.root / ".git")}
        self.config = {"server_url": "http://127.0.0.1:49374", "projects": [self.project],
                       "token_file": str(token), "data_dir": str(self.base / "data")}
        self.store = Store(self.root, self.base / "state")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def remote_note(self):
        identifier = memory.add(self.store, "verified sentinel", "local test", ["code.txt"])
        note = memory.inspect(self.store, identifier)
        self.store.db.execute("DELETE FROM notes")
        self.store.db.execute("DELETE FROM notes_fts")
        client = mock.Mock(project=self.project)
        client.search.return_value = [{"path": f"verified/{identifier}.md"}]
        client.read.return_value = {"project": "one", "workspace": "manacost", "body": json.dumps(note)}
        return note, client

    def test_registry_rejects_remote_urls(self):
        file = self.base / "registry.json"
        for url in ("https://example.com", "http://127.0.0.1@evil.test", "http://127.0.0.1/a",
                    "http://127.0.0.1?q=x", "http://localhost", "http://127.0.0.1/#x"):
            file.write_text(json.dumps(dict(self.config, server_url=url)))
            with self.subTest(url=url), self.assertRaises(ValueError):
                ai_memory.load_config(file)
        file.write_text(json.dumps(self.config))
        self.assertEqual(ai_memory.load_config(file), self.config)

    def test_credentials_not_inherited(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test", "ANTHROPIC_API_KEY": "test",
                                         "AI_MEMORY_LLM_PROVIDER": "openai", "HTTP_PROXY": "test"}):
            env = ai_memory.environment(self.config)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("AI_MEMORY_LLM_PROVIDER", env)
        self.assertNotIn("HTTP_PROXY", env)
        self.assertEqual("none", env["AI_MEMORY_EMBEDDING_PROVIDER"])

    def test_worktree_uses_common_git_identity(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test", "-c",
                        "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "fixture"], check=True)
        linked = self.base / "linked"
        subprocess.run(["git", "-C", str(self.root), "worktree", "add", "--detach", "-q", str(linked)], check=True)
        self.assertEqual(self.project, ai_memory.select_project(self.config, linked))
        self.assertIsNone(ai_memory.select_project(self.config, self.base))

    def test_hook_excludes_unselected_and_nonstartup_events(self):
        self.assertIsNone(hint({"hook_event_name": "SessionStart", "cwd": str(self.base)}, self.config))
        self.assertIsNone(hint({"hook_event_name": "PostToolUse", "cwd": str(self.root)}, self.config))
        result = hint({"hook_event_name": "SessionStart", "cwd": str(self.root),
                       "prompt": "NEVER-CAPTURE-THIS"}, self.config)
        encoded = json.dumps(result)
        self.assertNotIn("NEVER-CAPTURE-THIS", encoded)
        self.assertLess(len(encoded), 1500)

    def test_remote_note_revalidated_in_current_checkout(self):
        _, client = self.remote_note()
        with mock.patch.object(ai_memory, "client_for", return_value=client):
            self.assertEqual(1, len(ai_memory.search(self.store, "sentinel")))
            (self.root / "code.txt").write_text("changed")
            self.assertEqual([], ai_memory.search(self.store, "sentinel"))

    def test_remote_expired_note_excluded(self):
        note, client = self.remote_note()
        note.update(created=1, expires=2)
        client.read.return_value["body"] = json.dumps(note)
        with mock.patch.object(ai_memory, "client_for", return_value=client):
            self.assertEqual([], ai_memory.search(self.store, "sentinel"))

    def test_wrong_project_and_unverified_pages_excluded(self):
        _, client = self.remote_note()
        with mock.patch.object(ai_memory, "client_for", return_value=client):
            client.read.return_value["project"] = "another-project"
            self.assertEqual([], ai_memory.search(self.store, "sentinel"))
            client.search.return_value = [{"path": "sessions/automatic-summary.md"}]
            client.read.reset_mock()
            self.assertEqual([], ai_memory.search(self.store, "sentinel"))
            client.read.assert_not_called()

    def test_offline_search_and_mirror_preserve_local_notes(self):
        identifier = memory.add(self.store, "verified sentinel", "local test", ["code.txt"])
        with mock.patch.object(ai_memory, "client_for", side_effect=OSError("offline")):
            self.assertEqual("local; ai-memory unavailable", ai_memory.mirror(self.store, identifier))
            self.assertEqual(identifier, ai_memory.search(self.store, "sentinel")[0]["id"])

    def test_mirror_does_not_add_automatic_observations(self):
        identifier = memory.add(self.store, "verified sentinel", "local test", ["code.txt"])
        client = mock.Mock()
        with mock.patch.object(ai_memory, "client_for", return_value=client):
            self.assertEqual("local+ai-memory", ai_memory.mirror(self.store, identifier))
        path, body, _ = client.write.call_args.args
        self.assertEqual(f"verified/{identifier}.md", path)
        self.assertEqual({"id", "text", "evidence", "sources", "created", "expires"}, set(json.loads(body)))


if __name__ == "__main__":
    unittest.main()
