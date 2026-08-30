"""Monotonic clock types and the time provider implementation."""

import time
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class MonotonicTime:
    """A point on the monotonic clock as raw nanoseconds."""

    nanoseconds: int


class TimeProvider:
    """Provides the current monotonic clock value as a ``MonotonicTime``."""

    def now(self) -> MonotonicTime:
        return MonotonicTime(time.monotonic_ns())
