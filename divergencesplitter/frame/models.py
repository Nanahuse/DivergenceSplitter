"""Frame data models.

``Frame`` intentionally holds only the NumPy image array. Array copy and
ownership rules are guaranteed by each frame source implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from divergencesplitter.clock import MonotonicTime

ImageArray = np.ndarray


@dataclass(frozen=True)
class Frame:
    """A single captured frame carrying only its image array."""

    image: ImageArray


@dataclass
class FrameContext:
    frame: Frame
    now: MonotonicTime
    preprocessing_cache: dict[object, object] = field(default_factory=dict)
    detection_cache: dict[object, object] = field(default_factory=dict)
