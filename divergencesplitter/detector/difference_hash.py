"""DifferenceHashSimilarityDetector implementation."""

from __future__ import annotations

import numpy as np

from divergencesplitter.detector._configured import ConfiguredDetector
from divergencesplitter.detector.common import dhash_bits, frame_dhash, to_gray
from divergencesplitter.detector.models import (
    DetectionResult,
    DifferenceHashSimilarityConfig,
)
from divergencesplitter.frame.models import FrameContext


class DifferenceHashSimilarityDetector(
    ConfiguredDetector[DifferenceHashSimilarityConfig]
):
    """Perceptual-similarity detector using a difference hash (dHash).

    The grayscale image is resized to ``(hash_size + 1, hash_size)`` and hashed
    by comparing adjacent columns. The score is ``1 - hamming / hash_size**2``,
    so identical images score ``1.0`` and unrelated images approach ``0.0``.
    """

    __slots__ = ()

    def detect(self, context: FrameContext) -> DetectionResult:
        reference_hash = tuple(
            bool(value)
            for value in dhash_bits(
                to_gray(np.asarray(self.config.reference)), self.config.hash_size
            ).flat
        )
        frame_hash = tuple(
            bool(value) for value in frame_dhash(context, self.config.hash_size).flat
        )
        difference = sum(
            frame_bit != reference_bit
            for frame_bit, reference_bit in zip(frame_hash, reference_hash)
        )
        score = 1.0 - float(difference) / (self.config.hash_size**2)
        return DetectionResult(score=score)
