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
    ActionCandidate,
    DetectionResult,
    Frame,
    FrameContext,
    ImageArray,
    LiveSplitSnapshot,
    MonotonicTime,
    TimerOperation,
    TimerPhase,
)
from divergencesplitter.rule import Rule, RuleFrameEvaluation
from divergencesplitter.scenario import Scenario, process_scenarios
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
    "ActionCandidate",
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
    "LiveSplitSnapshot",
    "MeanBrightnessDetector",
    "MonotonicTime",
    "Not",
    "RisingEdge",
    "Rule",
    "RuleFrameEvaluation",
    "Scenario",
    "ScoreThreshold",
    "Then",
    "TimeProvider",
    "TimerOperation",
    "TimerPhase",
    "VideoFileDecodeError",
    "VideoFileEndOfFileError",
    "VideoFileError",
    "VideoFileOpenError",
    "VideoFileReadBeforeReadyError",
    "VideoFileSource",
    "evaluate",
    "process_scenarios",
]
