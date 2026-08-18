"""DivergenceSplitter public API."""

from divergencesplitter.detector import (
    FrameDifferenceDetector,
    ImageDetector,
    MeanBrightnessDetector,
    evaluate,
)
from divergencesplitter.frame_resize import resize_frame
from divergencesplitter.frame_source import ErrorAction, FrameSource, FrameSourceState
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
    VideoFileClipError,
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
    "ScoreThreshold",
    "TimeProvider",
    "VideoFileClipError",
    "VideoFileDecodeError",
    "VideoFileEndOfFileError",
    "VideoFileError",
    "VideoFileOpenError",
    "VideoFileReadBeforeReadyError",
    "VideoFileSource",
    "evaluate",
    "resize_frame",
]
