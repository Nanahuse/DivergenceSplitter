"""MeanBrightnessDetector implementation."""

from dataclasses import dataclass

from divergencesplitter.detector.common import frame_mean
from divergencesplitter.models import DetectionResult, FrameContext


@dataclass(frozen=True)
class MeanBrightnessDetector:
    """Level-style detector: matched when the frame mean is above ``threshold``."""

    threshold: float

    def detect(self, context: FrameContext) -> DetectionResult:
        mean = frame_mean(context)
        return DetectionResult(matched=mean > self.threshold, score=mean)
