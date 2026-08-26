"""ColorRangeDetector implementation."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from divergencesplitter.detector.models import (
    DetectionResult,
    Pixel,
    freeze_pixel_vector,
)
from divergencesplitter.frame.models import FrameContext


@dataclass(frozen=True)
class ColorRangeDetector:
    """Pixel-ratio detector using ``cv2.inRange`` (inclusive bounds).

    Reports the fraction of frame pixels whose value lies within
    ``[lower, upper]`` (both bounds inclusive) as score in ``[0.0, 1.0]``.
    ``lower`` and ``upper`` must share the same length, either ``1`` (a
    single-channel frame) or ``3`` (a three-channel frame).
    """

    lower: tuple[Pixel, ...]
    upper: tuple[Pixel, ...]

    def __post_init__(self) -> None:
        lower = freeze_pixel_vector(self.lower)
        upper = freeze_pixel_vector(self.upper)
        if len(lower) not in (1, 3):
            raise ValueError(f"color bound length must be 1 or 3, got {len(lower)}")
        if len(lower) != len(upper):
            raise ValueError(
                f"color bound length mismatch: {len(lower)} != {len(upper)}"
            )
        for lo, hi in zip(lower, upper):
            if lo > hi:
                raise ValueError(f"lower bound exceeds upper bound: {lower} > {upper}")
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)

    def detect(self, context: FrameContext) -> DetectionResult:
        frame = context.frame.image
        channels = len(self.lower)
        if frame.ndim == 2:
            frame_channels = 1
        elif frame.ndim == 3 and frame.shape[2] in (1, 3):
            frame_channels = frame.shape[2]
        else:
            raise ValueError(f"unsupported frame shape: {frame.shape}")
        if frame_channels != channels:
            raise ValueError(
                f"frame has {frame_channels} channels but bounds have {channels} values"
            )
        if not np.all(np.isfinite(frame)):
            raise ValueError("frame values must be finite")
        mask = cv2.inRange(frame, self.lower, self.upper)
        ratio = float(np.count_nonzero(mask)) / mask.size
        return DetectionResult(score=ratio)
