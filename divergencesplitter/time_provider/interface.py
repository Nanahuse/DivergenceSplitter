"""Time provider contract."""

from datetime import datetime
from typing import Protocol


class TimeProvider(Protocol):
    """Provides the current time as a timezone-aware ``datetime``.

    Implementations return an aware ``datetime`` and are responsible for their
    own monotonicity and precision guarantees.
    """

    def now(self) -> datetime: ...
