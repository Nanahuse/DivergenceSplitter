"""DifferenceHashSimilarityDetector implementation."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from divergencesplitter.detector.common import dhash_bits, frame_dhash, to_gray
from divergencesplitter.detector.models import (
    ConfigImage,
    DetectionResult,
    freeze_config_image,
)
from divergencesplitter.frame.models import FrameContext


@dataclass(frozen=True)
class DifferenceHashSimilarityDetector:
    """Perceptual-similarity detector using a difference hash (dHash).

    The grayscale image is resized to ``(hash_size + 1, hash_size)`` and hashed
    by comparing adjacent columns. The score is ``1 - hamming / hash_size**2``,
    so identical images score ``1.0`` and unrelated images approach ``0.0``.
    """

    reference: ConfigImage
    hash_size: int = 8
    _reference_hash: tuple[bool, ...] = field(
        init=False,
        repr=False,
        compare=False,
        hash=False,
    )

    def __post_init__(self) -> None:
        reference = freeze_config_image(self.reference)
        if type(self.hash_size) is not int or self.hash_size <= 0:
            raise ValueError(
                f"hash_size must be a positive integer: {self.hash_size!r}"
            )
        reference_bits = dhash_bits(to_gray(np.asarray(reference)), self.hash_size)
        object.__setattr__(self, "reference", reference)
        object.__setattr__(
            self,
            "_reference_hash",
            tuple(bool(value) for value in reference_bits.flat),
        )

    def detect(self, context: FrameContext) -> DetectionResult:
        frame_hash = tuple(
            bool(value) for value in frame_dhash(context, self.hash_size).flat
        )
        difference = sum(
            frame_bit != reference_bit
            for frame_bit, reference_bit in zip(frame_hash, self._reference_hash)
        )
        score = 1.0 - float(difference) / (self.hash_size**2)
        return DetectionResult(score=score)
