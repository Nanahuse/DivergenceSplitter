"""DivergenceSplitter public API."""

from divergencesplitter.detector import (
    FrameDifferenceDetector,
    ImageDetector,
    MeanBrightnessDetector,
    evaluate,
)
from divergencesplitter.frame_source import ErrorAction, FrameSource, FrameSourceState
from divergencesplitter.frame_transform import FrameCropResize
from divergencesplitter.models import (
    DetectionResult,
    Frame,
    FrameContext,
    ImageArray,
    MonotonicTime,
)
from divergencesplitter.score_threshold import ScoreThreshold
from divergencesplitter.time_provider import TimeProvider
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
    "FrameCropResize",
    "FrameDifferenceDetector",
    "FrameSource",
    "FrameSourceState",
    "ImageArray",
    "ImageDetector",
    "MeanBrightnessDetector",
    "MonotonicTime",
    "ScoreThreshold",
    "TimeProvider",
    "VideoFileDecodeError",
    "VideoFileEndOfFileError",
    "VideoFileError",
    "VideoFileOpenError",
    "VideoFileReadBeforeReadyError",
    "VideoFileSource",
    "evaluate",
]
