"""ColorRangeDetector implementation."""

from __future__ import annotations

import cv2
import numpy as np

from divergencesplitter.detector._configured import ConfiguredDetector
from divergencesplitter.detector.models import ColorRangeConfig, DetectionResult
from divergencesplitter.frame.models import FrameContext


class ColorRangeDetector(ConfiguredDetector[ColorRangeConfig]):
    """Pixel-ratio detector using ``cv2.inRange`` (inclusive bounds).

    Reports the fraction of frame pixels whose value lies within
    ``[lower, upper]`` (both bounds inclusive) as score in ``[0.0, 1.0]``.
    ``lower`` and ``upper`` must share the same length, either ``1`` (a
    single-channel frame) or ``3`` (a three-channel frame).
    """

    __slots__ = ()

    def detect(self, context: FrameContext) -> DetectionResult:
        frame = context.frame.image
        channels = len(self.config.lower)
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
        mask = cv2.inRange(frame, self.config.lower, self.config.upper)
        ratio = float(np.count_nonzero(mask)) / mask.size
        return DetectionResult(score=ratio)
