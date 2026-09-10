"""Prepared reference data shared by pixel similarity detectors."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from divergencesplitter.detector.common import frame_region
from divergencesplitter.detector.models import FrozenConfigImage, Region
from divergencesplitter.frame.models import FrameContext


@dataclass(frozen=True)
class PreparedSimilarityReference:
    image: np.ndarray
    mask: np.ndarray | None
    component_count: int


def prepare_similarity_reference(
    reference: FrozenConfigImage,
) -> PreparedSimilarityReference:
    source = np.asarray(reference)
    mask: np.ndarray | None = None
    if source.ndim == 3 and source.shape[2] == 4:
        valid = source[:, :, 3] > 0
        if not np.any(valid):
            raise ValueError("reference alpha mask has no valid pixels")
        mask = np.ascontiguousarray(valid.astype(np.uint8) * 255)
        source = source[:, :, :3]
    if source.ndim not in (2, 3):
        raise ValueError(f"unsupported reference shape: {source.shape}")
    if source.ndim == 3 and source.shape[2] not in (1, 3):
        raise ValueError(f"unsupported reference shape: {source.shape}")
    if np.issubdtype(source.dtype, np.integer) and source.min() >= 0 and source.max() <= 255:
        image = np.ascontiguousarray(source.astype(np.uint8, copy=False))
    else:
        image = np.ascontiguousarray(source.astype(np.float64, copy=False))
    pixels = int(np.count_nonzero(mask)) if mask is not None else image.shape[0] * image.shape[1]
    channels = 1 if image.ndim == 2 else image.shape[2]
    image.setflags(write=False)
    if mask is not None:
        mask.setflags(write=False)
    return PreparedSimilarityReference(image, mask, pixels * channels)


def similarity_error(
    context: FrameContext,
    prepared: PreparedSimilarityReference,
    region: Region | None,
    order: int,
) -> float:
    frame = frame_region(context, region)
    if np.issubdtype(frame.dtype, np.floating) and not np.all(np.isfinite(frame)):
        raise ValueError("frame values must be finite")
    if frame.shape != prepared.image.shape:
        raise ValueError(f"shape mismatch: {frame.shape} != {prepared.image.shape}")
    if prepared.mask is None and frame.dtype == prepared.image.dtype:
        norm_type = cv2.NORM_L1 if order == 1 else cv2.NORM_L2
        value = cv2.norm(frame, prepared.image, norm_type)
    else:
        left = frame.astype(np.float64, copy=False)
        right = prepared.image.astype(np.float64, copy=False)
        difference = left - right
        if order == 1:
            difference = np.abs(difference)
        else:
            difference = difference * difference
        if prepared.mask is not None:
            difference = difference[prepared.mask != 0]
        value = float(np.sum(difference)) if order == 1 else float(np.sqrt(np.sum(difference)))
    if order == 1:
        return float(value) / prepared.component_count
    return float(value) / float(np.sqrt(prepared.component_count))
