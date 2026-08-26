"""FrameDifferenceDetector implementation."""

from dataclasses import dataclass

from divergencesplitter.detector.common import frame_mean_abs_diff
from divergencesplitter.detector.models import ConfigImage, DetectionResult
from divergencesplitter.frame.models import FrameContext


@dataclass(frozen=True)
class FrameDifferenceDetector:
    """Frame-difference style detector: reports the mean absolute difference
    from ``reference`` as score."""

    reference: ConfigImage

    def detect(self, context: FrameContext) -> DetectionResult:
        diff = frame_mean_abs_diff(context, self.reference)
        return DetectionResult(score=diff)
