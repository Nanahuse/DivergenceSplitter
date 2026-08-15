"""DivergenceSplitter public API."""

from divergencesplitter.condition import DetectionCondition, ScoreThresholdCondition
from divergencesplitter.detector import (
    FrameDifferenceDetector,
    ImageDetector,
    MeanBrightnessDetector,
    evaluate,
)
from divergencesplitter.frame_source import ErrorAction, FrameSource, FrameSourceState
from divergencesplitter.models import DetectionResult, Frame, FrameContext, ImageArray
from divergencesplitter.video_file import (
    VideoFileDecodeError,
    VideoFileEndOfFileError,
    VideoFileError,
    VideoFileOpenError,
    VideoFileReadBeforeReadyError,
    VideoFileSource,
)

__all__ = [
    "DetectionCondition",
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
    "ScoreThresholdCondition",
    "VideoFileDecodeError",
    "VideoFileEndOfFileError",
    "VideoFileError",
    "VideoFileOpenError",
    "VideoFileReadBeforeReadyError",
    "VideoFileSource",
    "evaluate",
]
