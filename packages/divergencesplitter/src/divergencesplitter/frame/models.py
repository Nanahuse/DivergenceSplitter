"""Frame data models.

Array copy and ownership rules are guaranteed by each frame source
implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from divergencesplitter.clock import MonotonicTime

if TYPE_CHECKING:
    from divergencesplitter.detector.interface import ImageDetector
    from divergencesplitter.detector.models import DetectionResult

ImageArray = np.ndarray


@dataclass(frozen=True)
class Frame:
    """A captured image and its monotonic acquisition time."""

    image: ImageArray
    captured_at: MonotonicTime


@dataclass
class FrameContext:
    frame: Frame
    now: MonotonicTime
    preprocessing_cache: dict[object, object] = field(default_factory=dict)
    detection_cache: dict[ImageDetector, DetectionResult] = field(default_factory=dict)
