"""DifferenceHashSimilarityDetector implementation."""

from __future__ import annotations

import numpy as np

from divergencesplitter.detector._immutable import ImmutableDetector
from divergencesplitter.detector.common import dhash_bits, frame_dhash, to_gray
from divergencesplitter.detector.models import (
    ConfigImage,
    DetectionResult,
    freeze_config_image,
)
from divergencesplitter.frame.models import FrameContext


class DifferenceHashSimilarityDetector(ImmutableDetector):
    """Perceptual-similarity detector using a difference hash (dHash).

    The grayscale image is resized to ``(hash_size + 1, hash_size)`` and hashed
    by comparing adjacent columns. The score is ``1 - hamming / hash_size**2``,
    so identical images score ``1.0`` and unrelated images approach ``0.0``.
    """

    __slots__ = ("hash_size", "reference")

    reference: ConfigImage
    hash_size: int

    def __init__(self, reference: ConfigImage, hash_size: int = 8) -> None:
        reference = freeze_config_image(reference)
        if type(hash_size) is not int or hash_size <= 0:
            raise ValueError(f"hash_size must be a positive integer: {hash_size!r}")
        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "hash_size", hash_size)

    def _configuration_key(self) -> tuple[object, ...]:
        return (self.reference, self.hash_size)

    def detect(self, context: FrameContext) -> DetectionResult:
        reference_hash = tuple(
            bool(value)
            for value in dhash_bits(
                to_gray(np.asarray(self.reference)), self.hash_size
            ).flat
        )
        frame_hash = tuple(
            bool(value) for value in frame_dhash(context, self.hash_size).flat
        )
        difference = sum(
            frame_bit != reference_bit
            for frame_bit, reference_bit in zip(frame_hash, reference_hash)
        )
        score = 1.0 - float(difference) / (self.hash_size**2)
        return DetectionResult(score=score)
