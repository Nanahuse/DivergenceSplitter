"""Time provider interface and implementations."""

from divergencesplitter.time_provider.interface import TimeProvider
from divergencesplitter.time_provider.monotonic import MonotonicTimeProvider

__all__ = [
    "MonotonicTimeProvider",
    "TimeProvider",
]
