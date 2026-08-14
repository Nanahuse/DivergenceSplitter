"""Data models shared across the frame source boundary.

``Frame`` intentionally holds nothing but the image array: no timestamp,
capture time, media time, or sequence number. Array copy and ownership rules
are guaranteed by each frame source implementation.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Frame:
    """A single captured frame carrying only its image array."""

    image: np.ndarray
