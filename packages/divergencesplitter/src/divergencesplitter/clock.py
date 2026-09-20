"""Monotonic clock types and the time provider implementations.

Two different clocks are provided and deliberately kept type-distinct:

- :class:`TimeProvider` exposes monotonic wall-clock time as
  :class:`MonotonicTime`. It keeps advancing while a thread is descheduled or
  blocked, so it measures elapsed real time.
- :class:`ThreadTimeProvider` exposes the CPU time consumed by the calling
  thread as :class:`ThreadCpuTime`. It does not advance while the thread is
  stopped, waiting on a lock, or blocked on another thread's computation.
"""

import time
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class MonotonicTime:
    """A point on the monotonic wall-clock as raw nanoseconds."""

    nanoseconds: int


@dataclass(frozen=True, order=True)
class ThreadCpuTime:
    """A point on the calling thread's consumed-CPU clock as nanoseconds."""

    nanoseconds: int


class TimeProvider:
    """Provides the current monotonic wall-clock value as a ``MonotonicTime``."""

    def now(self) -> MonotonicTime:
        return MonotonicTime(time.monotonic_ns())


class ThreadTimeProvider:
    """Provides the calling thread's consumed CPU time as ``ThreadCpuTime``."""

    def now(self) -> ThreadCpuTime:
        return ThreadCpuTime(time.thread_time_ns())
