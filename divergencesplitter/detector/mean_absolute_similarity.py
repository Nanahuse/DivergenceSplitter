"""MeanAbsoluteSimilarityDetector implementation."""

from divergencesplitter.detector._immutable import ImmutableDetector
from divergencesplitter.detector.common import frame_mean_abs_diff
from divergencesplitter.detector.models import (
    ConfigImage,
    DetectionResult,
    freeze_config_image,
)
from divergencesplitter.frame.models import FrameContext


class MeanAbsoluteSimilarityDetector(ImmutableDetector):
    """Mean-absolute-similarity detector: reports the negated mean absolute
    difference from ``reference`` as score.

    The score follows the ``ImageDetector`` contract that higher values mean a
    stronger match: a perfect match scores ``0.0`` and larger differences
    produce smaller (more negative) scores.
    """

    __slots__ = ("reference",)

    reference: ConfigImage

    def __init__(self, reference: ConfigImage) -> None:
        object.__setattr__(self, "reference", freeze_config_image(reference))

    def _configuration_key(self) -> tuple[object, ...]:
        return (self.reference,)

    def detect(self, context: FrameContext) -> DetectionResult:
        diff = frame_mean_abs_diff(context, self.reference)
        return DetectionResult(score=-diff)
