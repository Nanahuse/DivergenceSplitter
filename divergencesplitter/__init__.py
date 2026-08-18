"""DivergenceSplitter public API."""

from divergencesplitter.detector import (
    FrameDifferenceDetector,
    ImageDetector,
    MeanBrightnessDetector,
    evaluate,
)
from divergencesplitter.frame_source import ErrorAction, FrameSource, FrameSourceState
from divergencesplitter.logic import (
    All,
    Any,
    FallingEdge,
    Hold,
    Not,
    RisingEdge,
    Then,
)
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
    "All",
    "Any",
    "DetectionResult",
    "ErrorAction",
    "FallingEdge",
    "Frame",
    "FrameContext",
    "FrameDifferenceDetector",
    "FrameSource",
    "FrameSourceState",
    "Hold",
    "ImageArray",
    "ImageDetector",
    "MeanBrightnessDetector",
    "MonotonicTime",
    "Not",
    "RisingEdge",
    "ScoreThreshold",
    "Then",
    "TimeProvider",
    "VideoFileDecodeError",
    "VideoFileEndOfFileError",
    "VideoFileError",
    "VideoFileOpenError",
    "VideoFileReadBeforeReadyError",
    "VideoFileSource",
    "evaluate",
]
