"""Data models shared by frame sources and image detectors.

``Frame`` intentionally holds only the NumPy image array. Array copy and
ownership rules are guaranteed by each frame source implementation. Detector
configuration values remain hashable so equivalent detectors can share cache
entries.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

Pixel = int | float
ConfigImage = Sequence[Sequence[Pixel]]
ImageArray = np.ndarray


@dataclass(frozen=True)
class Frame:
    """A single captured frame carrying only its image array."""

    image: ImageArray


@dataclass
class FrameContext:
    frame: Frame
    now: datetime
    preprocessing_cache: dict[object, object] = field(default_factory=dict)
    detection_cache: dict[object, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.now.utcoffset() is None:
            raise ValueError("FrameContext.now must be a timezone-aware datetime")


@dataclass(frozen=True)
class DetectionResult:
    """Data model holding the numeric observation of a single detector run.

    ``score`` is a required detector-specific measure with no cross-detector
    meaning.
    """

    score: float
