"""DivergenceSplitter public API."""

from divergencesplitter.detector import (
    FrameDifferenceDetector,
    ImageDetector,
    MeanBrightnessDetector,
    evaluate,
)
from divergencesplitter.frame_normalizer import (
    FrameClipError,
    FrameNormalizationError,
    FrameNormalizer,
    FrameResizeError,
)
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
    "FrameClipError",
    "FrameContext",
    "FrameDifferenceDetector",
    "FrameNormalizationError",
    "FrameNormalizer",
    "FrameResizeError",
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
