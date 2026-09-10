"""TemplateMatchConfig and TemplateMatchDetector."""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from divergencesplitter.detector._configured import ConfiguredDetector
from divergencesplitter.detector.models import (
    DetectionResult,
    FrozenConfigImage,
    ReferenceImage,
    Region,
    _validate_frozen_config_image,
)
from divergencesplitter.frame.models import FrameContext


@dataclass(frozen=True)
class TemplateMatchConfig:
    """Configuration for normalized template matching."""

    reference: FrozenConfigImage
    roi: Region | None = None

    def __post_init__(self) -> None:
        _validate_frozen_config_image(self.reference)
        template = np.asarray(self.reference, dtype=np.float32)
        if template.ndim == 3 and template.shape[2] == 4:
            if not np.any(template[:, :, 3] > 0):
                raise ValueError("template alpha mask has no valid pixels")
            template = template[:, :, :3]
        if np.all(np.ptp(template, axis=(0, 1)) == 0):
            raise ValueError("template must contain spatial variation")


class TemplateMatchDetector(ConfiguredDetector[TemplateMatchConfig]):
    """Normalized-cross-correlation template matcher.

    Slides ``reference`` over the frame and reports the maximum
    ``cv2.TM_CCOEFF_NORMED`` response as score. The score lies in ``[-1.0, 1.0]``
    where ``1.0`` is a perfect match. The reference must share the frame's
    channel layout and be no larger than the frame in either dimension.
    """

    @property
    def reference_images(self) -> tuple[ReferenceImage, ...]:
        return (ReferenceImage("reference", self.config.reference),)

    def detect(self, context: FrameContext) -> DetectionResult:
        from divergencesplitter.detector.common import frame_region

        frame = np.asarray(frame_region(context, self.config.roi))
        template = self._template
        mask = self._mask
        if np.issubdtype(frame.dtype, np.floating) and not np.all(np.isfinite(frame)):
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
        if frame.dtype != template.dtype:
            frame = frame.astype(template.dtype)
        response = (
            cv2.matchTemplate(frame, template, cv2.TM_CCORR_NORMED, mask=mask)
            if mask is not None
            else cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
        )
        score = float(np.max(response))
        if not math.isfinite(score):
            raise ValueError(f"template match produced non-finite score: {score}")
        return DetectionResult(score=score)
    def __init__(self, config: TemplateMatchConfig) -> None:
        super().__init__(config)
        reference = np.asarray(config.reference)
        mask = None
        if reference.ndim == 3 and reference.shape[2] == 4:
            valid = reference[:, :, 3] > 0
            if not np.any(valid):
                raise ValueError("template alpha mask has no valid pixels")
            mask = np.ascontiguousarray(valid.astype(np.uint8) * 255)
            reference = reference[:, :, :3]
        if np.issubdtype(reference.dtype, np.integer) and reference.min() >= 0 and reference.max() <= 255:
            template = np.ascontiguousarray(reference.astype(np.uint8, copy=False))
        else:
            template = np.ascontiguousarray(reference.astype(np.float32))
        template.setflags(write=False)
        if mask is not None:
            mask.setflags(write=False)
        self._template = template
        self._mask = mask
