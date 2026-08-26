"""PhaseCorrelationDetector implementation."""

from __future__ import annotations

import math

import cv2
import numpy as np

from divergencesplitter.detector._immutable import ImmutableDetector
from divergencesplitter.detector.common import frame_gray, to_gray
from divergencesplitter.detector.models import (
    ConfigImage,
    DetectionResult,
    freeze_config_image,
)
from divergencesplitter.frame.models import FrameContext


class PhaseCorrelationDetector(ImmutableDetector):
    """Phase-correlation detector.

    Converts the frame and ``reference`` to grayscale float32 and reports the
    peak response of ``cv2.phaseCorrelate`` as score; a higher score means a
    stronger match.

    Phase correlation measures the translational shift between two images, so a
    shifted copy of the reference also yields a high response. It therefore
    detects the same content regardless of where it appears in the frame, not
    positional equality.
    """

    __slots__ = ("reference",)

    reference: ConfigImage

    def __init__(self, reference: ConfigImage) -> None:
        object.__setattr__(self, "reference", freeze_config_image(reference))

    def _configuration_key(self) -> tuple[object, ...]:
        return (self.reference,)

    def detect(self, context: FrameContext) -> DetectionResult:
        frame = frame_gray(context)
        reference = to_gray(np.asarray(self.reference))
        if frame.shape != reference.shape:
            raise ValueError(
                f"shape mismatch: frame {frame.shape} != reference {reference.shape}"
            )
        _, response = cv2.phaseCorrelate(frame, reference)
        score = float(response)
        if not math.isfinite(score):
            raise ValueError(f"phase correlation produced non-finite response: {score}")
        return DetectionResult(score=score)
