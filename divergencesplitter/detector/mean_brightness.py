"""MeanBrightnessDetector implementation."""

from dataclasses import dataclass

from divergencesplitter.detector.common import frame_mean
from divergencesplitter.models import DetectionResult, FrameContext


@dataclass(frozen=True)
class MeanBrightnessDetector:
    """Level-style detector: reports the frame mean brightness as score."""

    def detect(self, context: FrameContext) -> DetectionResult:
        mean = frame_mean(context)
        return DetectionResult(score=mean)
