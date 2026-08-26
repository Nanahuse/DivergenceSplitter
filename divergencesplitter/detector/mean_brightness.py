"""MeanBrightnessDetector implementation."""

from divergencesplitter.detector.common import frame_mean
from divergencesplitter.detector.models import DetectionResult
from divergencesplitter.frame.models import FrameContext


class MeanBrightnessDetector:
    """Level-style detector: reports the frame mean brightness as score."""

    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MeanBrightnessDetector):
            return NotImplemented
        return True

    def __hash__(self) -> int:
        return hash(MeanBrightnessDetector)

    def detect(self, context: FrameContext) -> DetectionResult:
        mean = frame_mean(context)
        return DetectionResult(score=mean)
