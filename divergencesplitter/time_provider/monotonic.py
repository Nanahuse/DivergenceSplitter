"""Monotonic time provider implementation."""

import time
from datetime import UTC, datetime, timedelta


class MonotonicTimeProvider:
    """Provides a monotonic non-decreasing timezone-aware UTC time.

    On construction the provider reads the OS wall clock once as its display
    reference and records ``time.monotonic_ns()`` as the monotonic baseline.
    Every ``now`` call returns the reference UTC datetime plus the elapsed
    monotonic nanoseconds, so the wall clock is never read again and the
    returned time never moves backwards.

    Monotonic nanoseconds are truncated to microseconds because that is the
    finest resolution representable by ``datetime`` via ``timedelta``. Any
    sub-microsecond remainder is dropped, so calls within the same microsecond
    may return equal values; the result remains monotonic non-decreasing.
    """

    def __init__(self) -> None:
        self._reference_utc = datetime.now(UTC)
        self._monotonic_baseline_ns = time.monotonic_ns()

    def now(self) -> datetime:
        elapsed_ns = time.monotonic_ns() - self._monotonic_baseline_ns
        elapsed_us = elapsed_ns // 1000
        return self._reference_utc + timedelta(microseconds=elapsed_us)
