"""Fixed histogram similarity detector."""

from dataclasses import dataclass

import cv2
import numpy as np

from divergencesplitter.detector._configured import ConfiguredDetector
from divergencesplitter.detector.common import (
    _clamp_unit_score,
    frame_region,
    prepare_reference_alpha,
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
class HistogramSimilarityConfig:
    reference: FrozenConfigImage
    roi: Region | None = None

    def __post_init__(self) -> None:
        _validate_frozen_config_image(self.reference)


def _uint8_bgr(image: np.ndarray, label: str) -> np.ndarray:
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"{label} must be a 3-channel BGR image")
    if not np.all(np.isfinite(image)) or not np.all(image == np.floor(image)):
        raise ValueError(f"{label} pixels must be integer-valued")
    if image.size and (image.min() < 0 or image.max() > 255):
        raise ValueError(f"{label} pixels must be in range 0..255")
    return np.ascontiguousarray(image.astype(np.uint8, copy=False))


class HistogramSimilarityDetector(ConfiguredDetector[HistogramSimilarityConfig]):
    @property
    def reference_images(self) -> tuple[ReferenceImage, ...]:
        return (ReferenceImage("reference", self.config.reference),)

    def __init__(self, config: HistogramSimilarityConfig) -> None:
        super().__init__(config)
        image, mask = prepare_reference_alpha(np.asarray(config.reference))
        self._reference = _uint8_bgr(image, "reference")
        self._mask = mask
        self._histogram = self._calculate(self._reference, mask)

    @staticmethod
    def _calculate(image: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
        histogram = cv2.calcHist([image], [2, 1, 0], mask, [8, 8, 8], [0, 256] * 3)
        cv2.normalize(histogram, histogram)
        return histogram

    def detect(self, context: FrameContext) -> DetectionResult:
        frame = _uint8_bgr(np.asarray(frame_region(context, self.config.roi)), "frame")
        if self._mask is not None and frame.shape[:2] != self._mask.shape:
            raise ValueError("frame shape must match reference shape when masked")
        frame_hist = self._calculate(frame, self._mask)
        return DetectionResult(
            score=_clamp_unit_score(
                1.0
                - cv2.compareHist(
                    self._histogram, frame_hist, cv2.HISTCMP_BHATTACHARYYA
                )
            )
        )
