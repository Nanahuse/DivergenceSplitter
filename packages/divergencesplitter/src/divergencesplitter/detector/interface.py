"""ImageDetector contract.

The implementation contract is defined in the :class:`ImageDetector` protocol
docstring.
"""

from typing import Protocol

from divergencesplitter.detector.models import DetectionResult, ReferenceImage
from divergencesplitter.frame.models import FrameContext


class ImageDetector(Protocol):
    """Image detection method contract.

    Implementations evaluate ``context`` deterministically and return a
    ``DetectionResult``. They must be immutable and hashable by configuration
    value so equivalent definitions share one evaluation per frame.

    ``DetectionResult.score`` is detector-specific, and higher values always
    mean a stronger match. Built-in detectors generally map scores to
    ``[0.0, 1.0]`` when practical, but this is not required by the protocol.
    If the underlying library reports scores in the opposite direction, the
    implementation must invert the value inside ``detect`` so this contract
    holds.
    """

    @property
    def reference_images(self) -> tuple[ReferenceImage, ...]:
        """Read-only labeled reference images used for detection.

        Detectors without a reference image return an empty tuple.
        """
        ...

    def detect(self, context: FrameContext) -> DetectionResult: ...
