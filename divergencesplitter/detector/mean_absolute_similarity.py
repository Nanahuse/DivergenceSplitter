"""MeanAbsoluteSimilarityDetector implementation."""

from dataclasses import dataclass

from divergencesplitter.detector.common import frame_mean_abs_diff
from divergencesplitter.detector.models import (
    ConfigImage,
    DetectionResult,
    freeze_config_image,
)
from divergencesplitter.frame.models import FrameContext


@dataclass(frozen=True)
class MeanAbsoluteSimilarityDetector:
    """Mean-absolute-similarity detector: reports the negated mean absolute
    difference from ``reference`` as score.

    The score follows the ``ImageDetector`` contract that higher values mean a
    stronger match: a perfect match scores ``0.0`` and larger differences
    produce smaller (more negative) scores.
    """

    reference: ConfigImage

    def __post_init__(self) -> None:
        object.__setattr__(self, "reference", freeze_config_image(self.reference))

    def detect(self, context: FrameContext) -> DetectionResult:
        diff = frame_mean_abs_diff(context, self.reference)
        return DetectionResult(score=-diff)
