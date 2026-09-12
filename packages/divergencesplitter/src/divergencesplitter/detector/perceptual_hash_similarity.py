"""Fixed OpenCV perceptual-hash similarity detector."""

from dataclasses import dataclass

import cv2
import numpy as np

from divergencesplitter.detector._configured import ConfiguredDetector
from divergencesplitter.detector.common import frame_region, prepare_reference_alpha
from divergencesplitter.detector.histogram_similarity import _uint8_bgr
from divergencesplitter.detector.models import (
    DetectionResult,
    FrozenConfigImage,
    ReferenceImage,
    Region,
    _validate_frozen_config_image,
)
from divergencesplitter.frame.models import FrameContext


@dataclass(frozen=True)
class PerceptualHashSimilarityConfig:
    reference: FrozenConfigImage
    roi: Region | None = None

    def __post_init__(self) -> None:
        _validate_frozen_config_image(self.reference)


class PerceptualHashSimilarityDetector(
    ConfiguredDetector[PerceptualHashSimilarityConfig]
):
    def __init__(self, config: PerceptualHashSimilarityConfig) -> None:
        super().__init__(config)
        image, mask = prepare_reference_alpha(np.asarray(config.reference))
        self._reference = _uint8_bgr(image, "reference")
        self._mask = mask
        self._hash = self._compute(self._reference, mask)

    @property
    def reference_images(self) -> tuple[ReferenceImage, ...]:
        return (ReferenceImage("reference", self.config.reference),)

    @staticmethod
    def _compute(image: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
        if mask is not None:
            image = cv2.bitwise_and(image, image, mask=mask)
        resized = cv2.resize(image, (8, 8), interpolation=cv2.INTER_AREA)
        phash = cv2.img_hash.PHash_create()  # ty: ignore[unresolved-attribute]
        return phash.compute(resized)

    def detect(self, context: FrameContext) -> DetectionResult:
        frame = _uint8_bgr(np.asarray(frame_region(context, self.config.roi)), "frame")
        if self._mask is not None and frame.shape[:2] != self._mask.shape:
            raise ValueError("frame shape must match reference shape when masked")
        other_hash = self._compute(frame, self._mask)
        distance = int(np.unpackbits(np.bitwise_xor(self._hash, other_hash)).sum())
        return DetectionResult(score=1.0 - distance / 64.0)
