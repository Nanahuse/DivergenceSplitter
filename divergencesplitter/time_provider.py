"""Time provider implementation."""

import time

from divergencesplitter.models import MonotonicTime


class TimeProvider:
    """Provides the current monotonic clock value as a ``MonotonicTime``."""

    def now(self) -> MonotonicTime:
        return MonotonicTime(time.monotonic_ns())
