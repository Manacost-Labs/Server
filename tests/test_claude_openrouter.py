"""Claude Code receives only the credential from the private shared store."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HELPER = (Path(__file__).resolve().parents[1] /
          "integrations/codex/subscription-savings/bin/claude-openrouter-key")


class ClaudeOpenRouterTests(unittest.TestCase):
    def test_helper_reads_private_existing_credential_without_extra_output(self):
        with tempfile.TemporaryDirectory() as temp:
            credential = Path(temp) / ".config/codex-context-economy/remote.env"
            credential.parent.mkdir(parents=True)
            credential.write_text('OPENROUTER_API_KEY="test-key-only"\n')
            credential.chmod(0o600)
            env = {**os.environ, "HOME": temp, "OPENROUTER_API_KEY": "other-key"}
            result = subprocess.run([sys.executable, str(HELPER)], env=env,
                                    capture_output=True, text=True, check=True, timeout=5)
            self.assertEqual("test-key-only\n", result.stdout)
            self.assertEqual("", result.stderr)
