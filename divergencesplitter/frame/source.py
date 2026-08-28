"""Common frame source contract shared by all input implementations.

Source-specific connection, discovery, EOF, decode, memory ownership, and
reconnection behaviour is confined to each implementation. The common side
interprets errors no further than handing them back to their origin source.

``read`` performs pacing and decoding only and returns each raw frame exactly
as decoded, so un-evaluated frames are never transformed.
"""

from dataclasses import dataclass
from enum import Enum, auto
from types import TracebackType
from typing import Protocol, Self, TypeVar

from divergencesplitter.frame.models import Frame
from divergencesplitter.frame.normalizer import FrameNormalizer

ErrorT = TypeVar("ErrorT")


@dataclass(frozen=True)
class FrameReadResult[ErrorT]:
    """The mutually exclusive frame or error returned by a source read."""

    frame: Frame | None = None
    error: ErrorT | None = None

    def __post_init__(self) -> None:
        if (self.frame is None) == (self.error is None):
            raise ValueError("exactly one of frame and error must be set")


class FrameSourceState(Enum):
    """Whether ``read`` may currently be attempted."""

    NOT_READY = auto()
    READY = auto()


class ErrorAction(Enum):
    """Control signal a source returns for an error it has interpreted."""

    RETRY = auto()
    STOP = auto()


class FrameSource(Protocol[ErrorT]):
    """Input contract for obtaining raw frames."""

    @property
    def state(self) -> FrameSourceState: ...

    @property
    def normalizer(self) -> FrameNormalizer: ...

    def prepare(self) -> ErrorT | None: ...

    def read(self) -> FrameReadResult[ErrorT]: ...

    def handle_error(self, error: ErrorT) -> ErrorAction: ...

    def close(self) -> None: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
