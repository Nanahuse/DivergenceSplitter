"""DifferenceHashSimilarityConfig and DifferenceHashSimilarityDetector."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from divergencesplitter.detector._configured import ConfiguredDetector
from divergencesplitter.detector.common import dhash_bits, frame_dhash, to_gray
from divergencesplitter.detector.models import (
    DetectionResult,
    FrozenConfigImage,
    ReferenceImage,
    Region,
    _validate_frozen_config_image,
)
from divergencesplitter.frame.models import FrameContext


@dataclass(frozen=True)
class DifferenceHashSimilarityConfig:
    """Configuration for difference-hash similarity detection."""

    reference: FrozenConfigImage
    hash_size: int = 8
    roi: Region | None = None

    def __post_init__(self) -> None:
        _validate_frozen_config_image(self.reference)
        if self.hash_size <= 0:
            raise ValueError(
                f"hash_size must be a positive integer: {self.hash_size!r}"
            )


class DifferenceHashSimilarityDetector(
    ConfiguredDetector[DifferenceHashSimilarityConfig]
):
    """Perceptual-similarity detector using a difference hash (dHash).

    The grayscale image is resized to ``(hash_size + 1, hash_size)`` and hashed
    by comparing adjacent columns. The score is ``1 - hamming / hash_size**2``,
    so identical images score ``1.0`` and unrelated images approach ``0.0``.
    """

    @property
    def reference_images(self) -> tuple[ReferenceImage, ...]:
        return (ReferenceImage("reference", self.config.reference),)

    def detect(self, context: FrameContext) -> DetectionResult:
        frame_hash = frame_dhash(context, self.config.hash_size, self.config.roi)
        difference = int(
            np.count_nonzero(np.logical_xor(frame_hash, self._reference_hash))
        )
        score = 1.0 - float(difference) / (self.config.hash_size**2)
        return DetectionResult(score=score)

    def __init__(self, config: DifferenceHashSimilarityConfig) -> None:
        super().__init__(config)
        self._reference_hash = dhash_bits(
            to_gray(np.asarray(config.reference)), config.hash_size
        )
        self._reference_hash.setflags(write=False)
