"""ImageDetector interface, cache-aware evaluation, and detector implementations.

Detectors are immutable value objects: two equivalent instances compare equal
and hash equal. ``evaluate`` uses that to share a single ``DetectionResult``
per ``FrameContext`` even when the same definition appears as several
instances. Exceptions and non-``DetectionResult`` values are never cached.
"""

from divergencesplitter.detector.common import (
    FRAME_MEAN_KEY,
    evaluate,
    frame_mean,
    frame_mean_abs_diff,
    preprocessed,
)
from divergencesplitter.detector.frame_difference import FrameDifferenceDetector
from divergencesplitter.detector.interface import ImageDetector
from divergencesplitter.detector.mean_brightness import MeanBrightnessDetector

__all__ = [
    "FRAME_MEAN_KEY",
    "FrameDifferenceDetector",
    "ImageDetector",
    "MeanBrightnessDetector",
    "evaluate",
    "frame_mean",
    "frame_mean_abs_diff",
    "preprocessed",
]
