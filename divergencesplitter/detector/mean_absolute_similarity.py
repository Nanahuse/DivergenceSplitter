"""MeanAbsoluteSimilarityDetector implementation."""

from divergencesplitter.detector._configured import ConfiguredDetector
from divergencesplitter.detector.common import frame_mean_abs_diff
from divergencesplitter.detector.models import (
    DetectionResult,
    MeanAbsoluteSimilarityConfig,
)
from divergencesplitter.frame.models import FrameContext


class MeanAbsoluteSimilarityDetector(ConfiguredDetector[MeanAbsoluteSimilarityConfig]):
    """Mean-absolute-similarity detector: reports the negated mean absolute
    difference from ``reference`` as score.

    The score follows the ``ImageDetector`` contract that higher values mean a
    stronger match: a perfect match scores ``0.0`` and larger differences
    produce smaller (more negative) scores.
    """

    __slots__ = ()

    def detect(self, context: FrameContext) -> DetectionResult:
        diff = frame_mean_abs_diff(context, self.config.reference)
        return DetectionResult(score=-diff)
