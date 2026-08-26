"""ImageDetector interface, cache-aware evaluation, and detector implementations.

Detectors are immutable value objects: two equivalent instances compare equal
and hash equal. ``evaluate`` uses that to share a single ``DetectionResult``
per ``FrameContext`` even when the same definition appears as several
instances. Exceptions and non-``DetectionResult`` values are never cached.
"""

from divergencesplitter.detector.color_range import ColorRangeDetector
from divergencesplitter.detector.common import (
    FRAME_MEAN_KEY,
    evaluate,
    frame_mean,
    frame_mean_abs_diff,
    preprocessed,
)
from divergencesplitter.detector.difference_hash import DifferenceHashSimilarityDetector
from divergencesplitter.detector.interface import ImageDetector
from divergencesplitter.detector.mean_absolute_similarity import (
    MeanAbsoluteSimilarityDetector,
)
from divergencesplitter.detector.mean_brightness import MeanBrightnessDetector
from divergencesplitter.detector.models import (
    ColorRangeConfig,
    DifferenceHashSimilarityConfig,
    MeanAbsoluteSimilarityConfig,
    PhaseCorrelationConfig,
    TemplateMatchConfig,
)
from divergencesplitter.detector.phase_correlation import PhaseCorrelationDetector
from divergencesplitter.detector.template_match import TemplateMatchDetector

__all__ = [
    "FRAME_MEAN_KEY",
    "ColorRangeConfig",
    "ColorRangeDetector",
    "DifferenceHashSimilarityConfig",
    "DifferenceHashSimilarityDetector",
    "ImageDetector",
    "MeanAbsoluteSimilarityConfig",
    "MeanAbsoluteSimilarityDetector",
    "MeanBrightnessDetector",
    "PhaseCorrelationConfig",
    "PhaseCorrelationDetector",
    "TemplateMatchConfig",
    "TemplateMatchDetector",
    "evaluate",
    "frame_mean",
    "frame_mean_abs_diff",
    "preprocessed",
]
