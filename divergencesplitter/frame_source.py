"""Common frame source contract shared by all input implementations.

Source-specific connection, discovery, EOF, decode, memory ownership, and
reconnection behaviour is confined to each implementation. The common side
interprets errors no further than handing them back to their origin source.

Each concrete source keeps the image shape of its returned frames constant
across every successful ``read`` while READY; how that shape is determined is
source-specific.
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
    """Input-way-agnostic contract for obtaining ``Frame`` objects."""

    @property
    def state(self) -> FrameSourceState: ...

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
