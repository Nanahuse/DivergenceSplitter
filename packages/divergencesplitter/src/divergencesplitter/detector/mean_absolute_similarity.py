"""MeanAbsoluteSimilarityConfig and MeanAbsoluteSimilarityDetector."""

from dataclasses import dataclass

from divergencesplitter.detector._configured import ConfiguredDetector
from divergencesplitter.detector._similarity import (
    prepare_similarity_reference,
    similarity_error,
)
from divergencesplitter.detector.common import _clamp_unit_score
from divergencesplitter.detector.models import (
    DetectionResult,
    FrozenConfigImage,
    ReferenceImage,
    Region,
    _validate_frozen_config_image,
)
from divergencesplitter.frame.models import FrameContext


@dataclass(frozen=True)
class MeanAbsoluteSimilarityConfig:
    """Configuration for mean absolute similarity detection."""

    reference: FrozenConfigImage
    roi: Region | None = None

    def __post_init__(self) -> None:
        _validate_frozen_config_image(self.reference)


class MeanAbsoluteSimilarityDetector(ConfiguredDetector[MeanAbsoluteSimilarityConfig]):
    """Mean-absolute-similarity detector: reports the negated mean absolute
    difference from ``reference`` as score.

    The score follows the ``ImageDetector`` contract that higher values mean a
    stronger match: a perfect match scores ``0.0`` and larger differences
    produce smaller (more negative) scores.
    """

    def __init__(self, config: MeanAbsoluteSimilarityConfig) -> None:
        super().__init__(config)
        self._prepared = prepare_similarity_reference(config.reference)

    @property
    def reference_images(self) -> tuple[ReferenceImage, ...]:
        return (ReferenceImage("reference", self.config.reference),)

    def detect(self, context: FrameContext) -> DetectionResult:
        diff = similarity_error(context, self._prepared, self.config.roi, 1)
        key = (
            ("frame-mean-abs-diff", self.config.reference)
            if self.config.roi is None
            else (
                "frame-mean-abs-diff",
                self.config.reference,
                self.config.roi,
            )
        )
        context.preprocessing_cache.setdefault(key, diff)
        return DetectionResult(score=_clamp_unit_score(1.0 - diff / 255.0))
