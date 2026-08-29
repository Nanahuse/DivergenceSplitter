"""Common frame source contract shared by all input implementations.

Source-specific connection, discovery, EOF, decode, memory ownership, and
reconnection behaviour is confined to each implementation. The common side
interprets errors no further than handing them back to their origin source.

``read`` performs pacing and decoding only and returns each raw frame exactly
as decoded, so un-evaluated frames are never transformed.
"""

from enum import Enum, auto
from types import TracebackType
from typing import Protocol, Self, TypeVar, runtime_checkable

from divergencesplitter.frame.models import Frame
from divergencesplitter.frame.normalizer import FrameNormalizer

ErrorT = TypeVar("ErrorT")


class FrameSourceState(Enum):
    """Whether ``read`` may currently be attempted."""

    NOT_READY = auto()
    READY = auto()


class ErrorAction(Enum):
    """Control signal a source returns for an error it has interpreted."""

    RETRY = auto()
    STOP = auto()


@runtime_checkable
class FrameSource(Protocol[ErrorT]):
    """Input contract for obtaining raw frames."""

    @property
    def state(self) -> FrameSourceState: ...

    @property
    def normalizer(self) -> FrameNormalizer: ...

    def prepare(self) -> ErrorT | None: ...

    def read(self) -> Frame | ErrorT: ...

    def handle_error(self, error: ErrorT) -> ErrorAction: ...

    def close(self) -> None: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
