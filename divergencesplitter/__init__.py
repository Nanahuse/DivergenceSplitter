"""DivergenceSplitter public API."""

from divergencesplitter.condition import (
    All,
    Any,
    Detected,
    Elapsed,
    FallingEdge,
    Hold,
    Not,
    Nth,
    Once,
    RisingEdge,
    Then,
)
from divergencesplitter.detector import (
    FrameDifferenceDetector,
    ImageDetector,
    MeanBrightnessDetector,
    evaluate,
)
from divergencesplitter.frame_normalizer import (
    ClipRegion,
    FrameClipError,
    FrameNormalizationError,
    FrameNormalizer,
    FrameResizeError,
    OutputSize,
)
from divergencesplitter.frame_source import ErrorAction, FrameSource, FrameSourceState
from divergencesplitter.models import (
    DetectionResult,
    Frame,
    FrameContext,
    ImageArray,
    MonotonicTime,
)
from divergencesplitter.rule import Action, Condition, Rule
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
    "Action",
    "All",
    "Any",
    "ClipRegion",
    "Condition",
    "Detected",
    "DetectionResult",
    "Elapsed",
    "ErrorAction",
    "FallingEdge",
    "Frame",
    "FrameClipError",
    "FrameContext",
    "FrameDifferenceDetector",
    "FrameNormalizationError",
    "FrameNormalizer",
    "FrameResizeError",
    "FrameSource",
    "FrameSourceState",
    "Hold",
    "ImageArray",
    "ImageDetector",
    "MeanBrightnessDetector",
    "MonotonicTime",
    "Not",
    "Nth",
    "Once",
    "OutputSize",
    "RisingEdge",
    "Rule",
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
