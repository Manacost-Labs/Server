"""Exact current-session resolution for local task metering."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

INTEGRATION = Path(__file__).resolve().parents[1] / "integrations/codex/subscription-savings"
sys.path.insert(0, str(INTEGRATION))
from context_economy import meter  # noqa: E402


class CurrentSessionTests(unittest.TestCase):
    ID = "12345678-1234-1234-1234-123456789abc"

    def test_resolves_only_exact_session(self):
        with tempfile.TemporaryDirectory() as temp:
            sessions = Path(temp) / "sessions" / "2026" / "09" / "24"
            sessions.mkdir(parents=True)
            expected = sessions / f"rollout-2026-09-24T01-00-00-{self.ID}.jsonl"
            expected.write_text("")
            (sessions / "rollout-2026-09-24T02-00-00-other.jsonl").write_text("")
            with patch.dict(os.environ, {"CODEX_HOME": temp, "CODEX_SESSION_ID": self.ID}):
                self.assertEqual(expected, meter.current_session())

    def test_missing_invalid_and_ambiguous_id_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"CODEX_HOME": temp, "CODEX_SESSION_ID": "bad"}):
                with self.assertRaisesRegex(ValueError, "UUID"):
                    meter.current_session()
            with patch.dict(os.environ, {"CODEX_HOME": temp, "CODEX_SESSION_ID": self.ID}):
                with self.assertRaisesRegex(ValueError, "found 0"):
                    meter.current_session()
                for day in ("23", "24"):
                    folder = Path(temp) / "sessions" / "2026" / "09" / day
                    folder.mkdir(parents=True)
                    (folder / f"rollout-{day}-{self.ID}.jsonl").write_text("")
                with self.assertRaisesRegex(ValueError, "found 2"):
                    meter.current_session()
