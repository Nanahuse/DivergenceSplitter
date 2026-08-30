import unittest
from unittest import mock

from divergencesplitter.clock import TimeProvider

_BASELINE_NS = 1_000_000_000


class TimeProviderTest(unittest.TestCase):
    def test_now_stores_monotonic_ns_exactly(self):
        provider = TimeProvider()
        with mock.patch("divergencesplitter.clock.time.monotonic_ns") as monotonic_ns:
            monotonic_ns.return_value = _BASELINE_NS
            now = provider.now()
        self.assertEqual(now.nanoseconds, _BASELINE_NS)

    def test_consecutive_calls_return_ordered_monotonic_time(self):
        provider = TimeProvider()
        with mock.patch("divergencesplitter.clock.time.monotonic_ns") as monotonic_ns:
            monotonic_ns.return_value = _BASELINE_NS
            first = provider.now()
            monotonic_ns.return_value = _BASELINE_NS + 500
            second = provider.now()
        self.assertLess(first, second)


if __name__ == "__main__":
    unittest.main()
