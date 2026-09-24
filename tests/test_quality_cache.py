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

    def test_daily_counters_are_bounded_and_separate_from_lifetime_totals(self):
        with mock.patch("context_economy.quality_common.time.time", return_value=100):
            self.assertIsNone(cache_get(self.store, "search", "q"))
            cache_put(self.store, "search", "q", {"ok": True})
            self.assertIsNotNone(cache_get(self.store, "search", "q"))
        with mock.patch("context_economy.quality_common.time.time", return_value=86500):
            self.assertIsNone(cache_get(self.store, "search", "q"))
            result = cache_stats(self.store, days=2)
            self.assertEqual(["1970-01-01", "1970-01-02"],
                             [row["date_utc"] for row in result["daily"]["search"]])
            self.assertEqual(1, result["daily"]["search"][0]["hits"])
            self.assertEqual(1, result["daily"]["search"][1]["expired"])
            self.assertEqual(1, len(cache_stats(self.store, days=1)["daily"]["search"]))
        for days in (0, 31):
            with self.assertRaises(ValueError):
                cache_stats(self.store, days=days)


if __name__ == "__main__":
    unittest.main()
