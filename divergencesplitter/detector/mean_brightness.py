"""MeanBrightnessDetector implementation."""

from divergencesplitter.detector._immutable import ImmutableDetector
from divergencesplitter.detector.common import frame_mean
from divergencesplitter.detector.models import DetectionResult
from divergencesplitter.frame.models import FrameContext


class MeanBrightnessDetector(ImmutableDetector):
    """Level-style detector: reports the frame mean brightness as score."""

    __slots__ = ()

    def _configuration_key(self) -> tuple[object, ...]:
        return ()

    def detect(self, context: FrameContext) -> DetectionResult:
        mean = frame_mean(context)
        return DetectionResult(score=mean)
