"""Data models shared by frame sources and image detectors.

``Frame`` intentionally holds only the NumPy image array. Array copy and
ownership rules are guaranteed by each frame source implementation. Detector
configuration values remain hashable so equivalent detectors can share cache
entries.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

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
    now: float
    preprocessing_cache: dict[object, object] = field(default_factory=dict)
    detection_cache: dict[object, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionSample:
    """Result of a single detector evaluation.

    ``matched`` is the detector's boolean decision. ``score`` is a
    detector-specific measure with no cross-detector meaning; higher values
    always mean a stronger match (closer to ``matched=True``). ``score=None``
    means the detector provides no score. If the underlying library reports
    scores in the opposite direction, the detector must invert the value so
    this contract holds.
    """

    matched: bool
    score: float | None = None
