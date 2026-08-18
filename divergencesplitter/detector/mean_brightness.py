"""MeanBrightnessDetector implementation."""

from dataclasses import dataclass

from divergencesplitter.detector.common import frame_mean
from divergencesplitter.models import DetectionResult, FrameContext


@dataclass(frozen=True)
class MeanBrightnessDetector:
    """Level-style detector: reports the frame mean brightness as score.

    ``size`` is ``(width, height)`` in OpenCV order. When given, the frame is
    resized with ``cv2.INTER_LINEAR`` before the mean is computed.
    """

    size: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        if self.size is not None:
            width, height = self.size
            if width <= 0 or height <= 0:
                raise ValueError(f"size must be positive: {self.size}")

    def detect(self, context: FrameContext) -> DetectionResult:
        mean = frame_mean(context, self.size)
        return DetectionResult(score=mean)
