"""DivergenceSplitter public API."""

from divergencesplitter.detector import (
    FrameDifferenceDetector,
    ImageDetector,
    MeanBrightnessDetector,
    evaluate,
)
from divergencesplitter.frame_source import ErrorAction, FrameSource, FrameSourceState
from divergencesplitter.models import (
    DetectionResult,
    Frame,
    FrameContext,
    ImageArray,
    MonotonicTime,
)
from divergencesplitter.time_provider import TimeProvider
from divergencesplitter.trigger import ScoreThresholdTrigger, Trigger
from divergencesplitter.video_file import (
    VideoFileDecodeError,
    VideoFileEndOfFileError,
    VideoFileError,
    VideoFileOpenError,
    VideoFileReadBeforeReadyError,
    VideoFileSource,
)

__all__ = [
    "DetectionResult",
    "ErrorAction",
    "Frame",
    "FrameContext",
    "FrameDifferenceDetector",
    "FrameSource",
    "FrameSourceState",
    "ImageArray",
    "ImageDetector",
    "MeanBrightnessDetector",
    "MonotonicTime",
    "ScoreThresholdTrigger",
    "TimeProvider",
    "Trigger",
    "VideoFileDecodeError",
    "VideoFileEndOfFileError",
    "VideoFileError",
    "VideoFileOpenError",
    "VideoFileReadBeforeReadyError",
    "VideoFileSource",
    "evaluate",
]
