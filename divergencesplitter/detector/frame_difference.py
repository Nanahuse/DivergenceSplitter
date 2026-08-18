"""FrameDifferenceDetector implementation."""

from dataclasses import dataclass

from divergencesplitter.detector.common import frame_mean_abs_diff
from divergencesplitter.models import ConfigImage, DetectionResult, FrameContext


@dataclass(frozen=True)
class FrameDifferenceDetector:
    """Frame-difference style detector: reports the mean absolute difference
    from ``reference`` as score.

    ``size`` is ``(width, height)`` in OpenCV order. When given, the frame is
    resized with ``cv2.INTER_LINEAR`` before comparison; ``reference`` must
    then match the resized shape.
    """

    reference: ConfigImage
    size: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        if self.size is not None:
            width, height = self.size
            if width <= 0 or height <= 0:
                raise ValueError(f"size must be positive: {self.size}")

    def detect(self, context: FrameContext) -> DetectionResult:
        diff = frame_mean_abs_diff(context, self.reference, self.size)
        return DetectionResult(score=diff)
