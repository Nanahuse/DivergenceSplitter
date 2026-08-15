"""FrameDifferenceDetector implementation."""

from dataclasses import dataclass

from divergencesplitter.detector.common import frame_mean_abs_diff
from divergencesplitter.models import ConfigImage, DetectionResult, FrameContext


@dataclass(frozen=True)
class FrameDifferenceDetector:
    """Frame-difference style detector: matched when the frame differs from
    ``reference`` by at least ``threshold`` (mean absolute difference)."""

    reference: ConfigImage
    threshold: float

    def detect(self, context: FrameContext) -> DetectionResult:
        diff = frame_mean_abs_diff(context, self.reference)
        return DetectionResult(matched=diff >= self.threshold, score=diff)
