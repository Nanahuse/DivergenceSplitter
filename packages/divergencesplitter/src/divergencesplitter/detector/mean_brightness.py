"""MeanBrightnessDetector implementation."""

from dataclasses import dataclass

from divergencesplitter.detector.common import frame_mean_region
from divergencesplitter.detector.models import DetectionResult, ReferenceImage, Region
from divergencesplitter.frame.models import FrameContext


@dataclass(frozen=True)
class MeanBrightnessDetector:
    """Level-style detector: reports the frame mean brightness as score."""

    @property
    def reference_images(self) -> tuple[ReferenceImage, ...]:
        return ()

    roi: Region | None = None

    def detect(self, context: FrameContext) -> DetectionResult:
        mean = frame_mean_region(context, self.roi)
        return DetectionResult(score=mean)
