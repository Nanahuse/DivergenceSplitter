"""Detector configuration and result data models.

Detector configuration values remain hashable so equivalent detectors can
share cache entries.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

Pixel = int | float
ConfigImage = Sequence[Sequence[Pixel]]


@dataclass(frozen=True)
class DetectionResult:
    """Data model holding the numeric observation of a single detector run.

    ``score`` is a required detector-specific measure with no cross-detector
    meaning.
    """

    score: float
