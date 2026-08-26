"""TemplateMatchDetector implementation."""

from __future__ import annotations

import math

import cv2
import numpy as np

from divergencesplitter.detector._configured import ConfiguredDetector
from divergencesplitter.detector.models import DetectionResult, TemplateMatchConfig
from divergencesplitter.frame.models import FrameContext


class TemplateMatchDetector(ConfiguredDetector[TemplateMatchConfig]):
    """Normalized-cross-correlation template matcher.

    Slides ``reference`` over the frame and reports the maximum
    ``cv2.TM_CCOEFF_NORMED`` response as score. The score lies in ``[-1.0, 1.0]``
    where ``1.0`` is a perfect match. The reference must share the frame's
    channel layout and be no larger than the frame in either dimension.
    """

    __slots__ = ()

    def detect(self, context: FrameContext) -> DetectionResult:
        frame = np.asarray(context.frame.image, dtype=np.float32)
        template = np.asarray(self.config.reference, dtype=np.float32)
        if not np.all(np.isfinite(frame)):
            raise ValueError("frame values must be finite")
        if frame.ndim != template.ndim:
            raise ValueError(
                "channel layout mismatch: "
                f"frame has {frame.ndim} dims, template has {template.ndim} dims"
            )
        if frame.ndim == 3 and frame.shape[2] != template.shape[2]:
            raise ValueError(
                "channel count mismatch: "
                f"frame has {frame.shape[2]} channels, template has {template.shape[2]}"
            )
        if template.shape[0] > frame.shape[0] or template.shape[1] > frame.shape[1]:
            raise ValueError(
                f"template {template.shape[:2]} larger than frame {frame.shape[:2]}"
            )
        response = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
        score = float(np.max(response))
        if not math.isfinite(score):
            raise ValueError(f"template match produced non-finite score: {score}")
        return DetectionResult(score=score)
