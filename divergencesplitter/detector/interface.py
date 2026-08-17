"""ImageDetector contract.

The implementation contract is defined in the :class:`ImageDetector` protocol
docstring.
"""

from typing import Protocol

from divergencesplitter.models import DetectionResult, FrameContext


class ImageDetector(Protocol):
    """Image detection method contract.

    Implementations evaluate ``context`` deterministically and return a
    ``DetectionResult``. They must be immutable and hashable by configuration
    value so equivalent definitions share one evaluation per frame.

    ``DetectionResult.score`` is a detector-specific measure, not normalized or
    comparable across detectors. Higher values always mean a stronger match.
    If the underlying library reports scores in the opposite direction, the
    implementation must invert the value inside ``detect`` so this contract
    holds.
    """

    def detect(self, context: FrameContext) -> DetectionResult: ...
