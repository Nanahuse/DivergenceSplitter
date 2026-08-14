"""ImageDetector contract.

Implementations evaluate ``context`` deterministically and return a
``DetectionSample``. They must be immutable and hashable by configuration
value so equivalent definitions share one evaluation per frame.
"""

from typing import Protocol

from divergencesplitter.models import DetectionSample, FrameContext


class ImageDetector(Protocol):
    """Image detection method contract.

    Implementations evaluate ``context`` deterministically and return a
    ``DetectionSample``. They must be immutable and hashable by configuration
    value so equivalent definitions share one evaluation per frame.
    """

    def detect(self, context: FrameContext) -> DetectionSample: ...
