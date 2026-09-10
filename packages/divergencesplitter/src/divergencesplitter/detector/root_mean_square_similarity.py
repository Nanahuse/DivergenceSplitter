"""RootMeanSquareSimilarityConfig and RootMeanSquareSimilarityDetector."""

from dataclasses import dataclass

import numpy as np

from divergencesplitter.detector._configured import ConfiguredDetector
from divergencesplitter.detector._similarity import (
    prepare_similarity_reference,
    similarity_error,
)
from divergencesplitter.detector.models import (
    DetectionResult,
    FrozenConfigImage,
    ReferenceImage,
    Region,
    _validate_frozen_config_image,
)
from divergencesplitter.frame.models import FrameContext


@dataclass(frozen=True)
class RootMeanSquareSimilarityConfig:
    """Configuration for normalized root-mean-square similarity detection."""

    reference: FrozenConfigImage
    roi: Region | None = None

    def __post_init__(self) -> None:
        _validate_frozen_config_image(self.reference)
        reference = np.asarray(self.reference)
        if reference.ndim == 3 and reference.shape[2] == 4 and not np.any(reference[:, :, 3] > 0):
            raise ValueError("reference alpha mask has no valid pixels")


class RootMeanSquareSimilarityDetector(
    ConfiguredDetector[RootMeanSquareSimilarityConfig]
):
    """Detector whose score is the negative RMSE from the reference."""

    def __init__(self, config: RootMeanSquareSimilarityConfig) -> None:
        super().__init__(config)
        self._prepared = prepare_similarity_reference(config.reference)

    @property
    def reference_images(self) -> tuple[ReferenceImage, ...]:
        return (ReferenceImage("reference", self.config.reference),)

    def detect(self, context: FrameContext) -> DetectionResult:
        error = similarity_error(context, self._prepared, self.config.roi, 2)
        return DetectionResult(score=-error)
