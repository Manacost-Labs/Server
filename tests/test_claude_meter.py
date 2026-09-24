"""Claude Code session metering counts each API request once."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

INTEGRATION = Path(__file__).resolve().parents[1] / "integrations/codex/subscription-savings"
sys.path.insert(0, str(INTEGRATION))
from context_economy import meter  # noqa: E402
from context_economy.common import Store  # noqa: E402


class ClaudeMeterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root, self.root / "state")
        self.session = self.root / "session.jsonl"

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def add(self, request, *, inp, created=0, cached=0, out=0, thinking=0,
            block="text", tool_id=None, include_cache=True):
        usage = {"input_tokens": inp, "cache_creation_input_tokens": created,
                 "output_tokens": out, "output_tokens_details": {"thinking_tokens": thinking}}
        if include_cache:
            usage["cache_read_input_tokens"] = cached
        content = [{"type": block, **({"id": tool_id} if tool_id else {})}]
        item = {"type": "assistant", "requestId": request,
                "message": {"id": request, "model": "claude-haiku-test", "usage": usage,
                            "content": content}, "effort": "low"}
        with self.session.open("a") as stream:
            stream.write(json.dumps(item) + "\n")

    def test_interval_deduplicates_streamed_blocks_and_preserves_cache_totals(self):
        self.add("req-old", inp=3, created=4, cached=5, out=2)
        self.add("req-old", inp=3, created=4, cached=5, out=2)
        meter.start(self.store, "claude-task", self.session, session_format="claude")
        self.add("req-old", inp=3, created=4, cached=5, out=2)
        self.add("req-new", inp=10, created=20, cached=30, out=8, thinking=3)
        self.add("req-new", inp=10, created=20, cached=30, out=8, thinking=3,
                 block="tool_use", tool_id="tool-1")
        value = meter.report(self.store, "claude-task")
        self.assertEqual((60, 30, 8, 3, 1),
                         tuple(value[name] for name in ("input_tokens", "cached_input_tokens",
                                                         "output_tokens", "reasoning_tokens", "tool_calls")))
        self.assertEqual("claude", value["session_components"][0]["session_format"])
        self.assertEqual(60, meter.report(self.store, "claude-task")["input_tokens"])

    def test_incomplete_usage_is_unknown_instead_of_undercounted(self):
        self.session.write_text("")
        meter.start(self.store, "claude-task", self.session, session_format="claude")
        self.add("req-new", inp=4, out=2, include_cache=False)
        value = meter.report(self.store, "claude-task")
        self.assertIsNone(value["input_tokens"])
        self.assertIsNone(value["output_tokens"])

    def test_attached_claude_helper_is_included_once(self):
        self.session.write_text("")
        meter.start(self.store, "claude-task", self.session, session_format="claude")
        helper = self.root / "helper.jsonl"
        helper.write_text("")
        meter.attach(self.store, "claude-task", helper, "helper", session_format="claude")
        self.add("req-primary", inp=2, out=1)
        self.session = helper
        self.add("req-helper", inp=5, created=3, cached=2, out=4)
        self.add("req-helper", inp=5, created=3, cached=2, out=4)
        value = meter.report(self.store, "claude-task")
        self.assertEqual((12, 2, 5),
                         tuple(value[name] for name in ("input_tokens", "cached_input_tokens", "output_tokens")))
        self.assertEqual(["primary", "helper"], [part["role"] for part in value["session_components"]])

    def test_requires_bounded_initial_session(self):
        self.session.write_bytes(b" " * (meter.WINDOW + 1))
        with self.assertRaisesRegex(ValueError, "new Claude session"):
            meter.start(self.store, "claude-task", self.session, session_format="claude")
