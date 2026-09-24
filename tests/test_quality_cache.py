"""Persistent cache counters distinguish real lookups from cache writes."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

INTEGRATION = Path(__file__).resolve().parents[1] / "integrations/codex/subscription-savings"
sys.path.insert(0, str(INTEGRATION))
from context_economy.common import Store  # noqa: E402
from context_economy.quality_common import cache_get, cache_put, cache_stats  # noqa: E402


class QualityCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root, self.root / "state")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_hits_misses_expiry_and_writes_are_separate(self):
        with mock.patch("context_economy.quality_common.time.time", return_value=100):
            self.assertIsNone(cache_get(self.store, "search", "q"))
            cache_put(self.store, "search", "q", {"ok": True})
            self.assertEqual({"ok": True}, cache_get(self.store, "search", "q"))
        with mock.patch("context_economy.quality_common.time.time", return_value=86500):
            self.assertIsNone(cache_get(self.store, "search", "q"))
        row = cache_stats(self.store)["namespaces"]["search"]
        self.assertEqual({"hits": 1, "misses": 1, "expired": 1, "writes": 1, "evictions": 0,
                          "entries": 1}, row)

    def test_global_limit_reports_evictions_by_namespace(self):
        with mock.patch("context_economy.quality_common.time.time", side_effect=range(1001)):
            for index in range(1001):
                cache_put(self.store, "search", str(index), index)
        row = cache_stats(self.store)["namespaces"]["search"]
        self.assertEqual(1000, row["entries"])
        self.assertEqual(1, row["evictions"])
        self.assertEqual(1001, row["writes"])


if __name__ == "__main__":
    unittest.main()
