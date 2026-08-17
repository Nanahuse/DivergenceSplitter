import unittest
from datetime import UTC, timedelta
from unittest import mock

from divergencesplitter.time_provider import MonotonicTimeProvider

_BASELINE_NS = 1_000_000_000


class MonotonicTimeProviderTest(unittest.TestCase):
    def test_now_returns_aware_utc_datetime(self):
        provider = MonotonicTimeProvider()
        now = provider.now()
        self.assertIs(now.tzinfo, UTC)
        self.assertEqual(now.utcoffset(), timedelta(0))

    def test_now_converts_monotonic_elapsed_to_datetime(self):
        with mock.patch(
            "divergencesplitter.time_provider.monotonic.time.monotonic_ns"
        ) as monotonic_ns:
            monotonic_ns.return_value = _BASELINE_NS
            provider = MonotonicTimeProvider()
            first = provider.now()
            monotonic_ns.return_value = _BASELINE_NS + 2_500_000_000
            second = provider.now()
        self.assertEqual(second - first, timedelta(seconds=2, microseconds=500000))

    def test_now_truncates_sub_microsecond_remainder(self):
        with mock.patch(
            "divergencesplitter.time_provider.monotonic.time.monotonic_ns"
        ) as monotonic_ns:
            monotonic_ns.return_value = _BASELINE_NS
            provider = MonotonicTimeProvider()
            first = provider.now()
            monotonic_ns.return_value = _BASELINE_NS + 1_999
            second = provider.now()
        self.assertEqual(second - first, timedelta(microseconds=1))

    def test_now_is_monotonic_non_decreasing(self):
        with mock.patch(
            "divergencesplitter.time_provider.monotonic.time.monotonic_ns"
        ) as monotonic_ns:
            monotonic_ns.return_value = _BASELINE_NS
            provider = MonotonicTimeProvider()
            first = provider.now()
            monotonic_ns.return_value = _BASELINE_NS + 500
            second = provider.now()
            monotonic_ns.return_value = _BASELINE_NS + 1_000
            third = provider.now()
        self.assertEqual(first, second)
        self.assertLess(second, third)


if __name__ == "__main__":
    unittest.main()
