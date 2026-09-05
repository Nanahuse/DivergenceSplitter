"""MeanAbsoluteSimilarityConfig and MeanAbsoluteSimilarityDetector."""

from dataclasses import dataclass

from divergencesplitter.detector._configured import ConfiguredDetector
from divergencesplitter.detector.common import frame_mean_abs_diff
from divergencesplitter.detector.models import (
    DetectionResult,
    FrozenConfigImage,
    ReferenceImage,
    _validate_frozen_config_image,
)
from divergencesplitter.frame.models import FrameContext


@dataclass(frozen=True)
class MeanAbsoluteSimilarityConfig:
    """Configuration for mean absolute similarity detection."""

    reference: FrozenConfigImage

    def __post_init__(self) -> None:
        _validate_frozen_config_image(self.reference)


class MeanAbsoluteSimilarityDetector(ConfiguredDetector[MeanAbsoluteSimilarityConfig]):
    """Mean-absolute-similarity detector: reports the negated mean absolute
    difference from ``reference`` as score.

    The score follows the ``ImageDetector`` contract that higher values mean a
    stronger match: a perfect match scores ``0.0`` and larger differences
    produce smaller (more negative) scores.
    """

    @property
    def reference_images(self) -> tuple[ReferenceImage, ...]:
        return (ReferenceImage("reference", self.config.reference),)

    def detect(self, context: FrameContext) -> DetectionResult:
        diff = frame_mean_abs_diff(context, self.config.reference)
        return DetectionResult(score=-diff)
