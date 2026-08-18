"""Common frame source contract shared by all input implementations.

Source-specific connection, discovery, EOF, decode, memory ownership, and
reconnection behaviour is confined to each implementation. The common side
interprets errors no further than handing them back to their origin source.

``read`` performs pacing and decoding only and returns each frame exactly as
decoded, so un-evaluated frames are never transformed. For raw frames read
from one prepared stream, a concrete source's successful ``normalize`` results
have a stable image shape; that shape is fixed by the source configuration and
how it is determined is source-specific.
"""

from enum import Enum, auto
from types import TracebackType
from typing import Protocol, Self, TypeVar

from divergencesplitter.models import Frame

ErrorT = TypeVar("ErrorT")


class FrameSourceState(Enum):
    """Whether ``read`` may currently be attempted."""

    NOT_READY = auto()
    READY = auto()


class ErrorAction(Enum):
    """Control signal a source returns for an error it has interpreted."""

    RETRY = auto()
    STOP = auto()


class FrameSource(Protocol[ErrorT]):
    """Input-way-agnostic contract for obtaining ``Frame`` objects.

    Evaluation code decides which frame to evaluate and then calls ``normalize``
    at most once on it, sharing the result with every detector as a single
    ``FrameContext``. ``normalize`` is pure: it neither reads nor changes the
    source state, and may be called after ``close``. Its input must be a raw
    ``Frame`` previously returned by that same source.
    """

    @property
    def state(self) -> FrameSourceState: ...

    def prepare(self) -> ErrorT | None: ...

    def read(self) -> Frame | ErrorT: ...

    def normalize(self, frame: Frame) -> Frame | ErrorT: ...

    def handle_error(self, error: ErrorT) -> ErrorAction: ...

    def close(self) -> None: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
