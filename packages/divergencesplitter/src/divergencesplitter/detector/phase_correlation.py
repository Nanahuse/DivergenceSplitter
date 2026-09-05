"""PhaseCorrelationConfig and PhaseCorrelationDetector."""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from divergencesplitter.detector._configured import ConfiguredDetector
from divergencesplitter.detector.common import frame_gray, to_gray
from divergencesplitter.detector.models import (
    DetectionResult,
    FrozenConfigImage,
    ReferenceImage,
    _validate_frozen_config_image,
)
from divergencesplitter.frame.models import FrameContext


@dataclass(frozen=True)
class PhaseCorrelationConfig:
    """Configuration for phase-correlation detection."""

    reference: FrozenConfigImage

    def __post_init__(self) -> None:
        _validate_frozen_config_image(self.reference)


class PhaseCorrelationDetector(ConfiguredDetector[PhaseCorrelationConfig]):
    """Phase-correlation detector.

    Converts the frame and ``reference`` to grayscale float32 and reports the
    peak response of ``cv2.phaseCorrelate`` as score; a higher score means a
    stronger match.

    Phase correlation measures the translational shift between two images, so a
    shifted copy of the reference also yields a high response. It therefore
    detects the same content regardless of where it appears in the frame, not
    positional equality.
    """

    @property
    def reference_images(self) -> tuple[ReferenceImage, ...]:
        return (ReferenceImage("reference", self.config.reference),)

    def detect(self, context: FrameContext) -> DetectionResult:
        frame = frame_gray(context)
        reference = to_gray(np.asarray(self.config.reference))
        if frame.shape != reference.shape:
            raise ValueError(
                f"shape mismatch: frame {frame.shape} != reference {reference.shape}"
            )
        _, response = cv2.phaseCorrelate(frame, reference)
        score = float(response)
        if not math.isfinite(score):
            raise ValueError(f"phase correlation produced non-finite response: {score}")
        return DetectionResult(score=score)
