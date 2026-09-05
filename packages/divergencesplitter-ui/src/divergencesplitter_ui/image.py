"""Image conversion and texture lifecycle decisions for the main screen.

This module is free of any Dear PyGui import so both the pixel conversion and
the create/update/recreate decision can be exercised as pure behavior in tests
that run without a GPU or a GUI. The renderer owns the actual texture handles
and calls into these helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

import numpy as np
from divergencesplitter.detector.models import FrozenConfigImage


@dataclass(frozen=True)
class TextureSignature:
    """The display-relevant shape and source channel count of one image."""

    height: int
    width: int
    source_channels: int


class TextureEvent(Enum):
    """How the renderer should reconcile a texture with an incoming image."""

    CREATE = auto()
    UPDATE = auto()
    RECREATE = auto()


def source_signature(image: np.ndarray) -> TextureSignature:
    """Describe an image by its height, width, and source channel count."""

    array = np.asarray(image)
    if array.ndim == 2:
        channels = 1
    elif array.ndim == 3:
        channels = array.shape[2]
    else:
        raise ValueError(f"unsupported image dimensionality: {array.ndim}")
    return TextureSignature(
        height=int(array.shape[0]),
        width=int(array.shape[1]),
        source_channels=int(channels),
    )


def plan_texture(
    previous: TextureSignature | None,
    current: TextureSignature,
) -> TextureEvent:
    """Decide whether to create, update in place, or recreate a texture.

    A texture only exists when ``previous`` is not ``None``. A matching
    signature means the existing GPU buffer can be updated in place; any change
    in height, width, or source channel count requires deleting and recreating
    the texture so the GPU layout stays consistent.
    """

    if previous is None:
        return TextureEvent.CREATE
    if previous == current:
        return TextureEvent.UPDATE
    return TextureEvent.RECREATE


def to_rgba_float32(image: np.ndarray) -> np.ndarray:
    """Convert a raw image to a contiguous RGBA float32 array in ``[0, 1]``.

    Accepts the frame layouts produced by the runtime: two-dimensional
    single-channel (gray), three-channel BGR, singleton-channel, and
    four-channel BGRA. Integer data is scaled by its full range and float data
    is clamped to ``[0, 1]``. The result is ready for a
    ``mvFormat_Float_rgba`` dynamic/raw texture.
    """

    array = np.asarray(image)
    if array.ndim == 2:
        rgb = np.stack((array, array, array), axis=-1)
        alpha = None
    elif array.ndim == 3 and array.shape[2] == 1:
        gray = array[:, :, 0]
        rgb = np.stack((gray, gray, gray), axis=-1)
        alpha = None
    elif array.ndim == 3 and array.shape[2] == 3:
        rgb = array[:, :, ::-1]
        alpha = None
    elif array.ndim == 3 and array.shape[2] == 4:
        rgb = array[:, :, 2::-1]
        alpha = array[:, :, 3]
    else:
        raise ValueError(f"unsupported image shape: {array.shape}")

    rgba = np.zeros((rgb.shape[0], rgb.shape[1], 4), dtype=np.float64)
    if np.issubdtype(array.dtype, np.integer):
        scale = 1.0 / np.iinfo(array.dtype).max
        rgba[:, :, :3] = rgb * scale
        rgba[:, :, 3] = 1.0 if alpha is None else alpha * scale
    else:
        rgba[:, :, :3] = np.clip(rgb, 0.0, 1.0)
        rgba[:, :, 3] = 1.0 if alpha is None else np.clip(alpha, 0.0, 1.0)
    return rgba.astype(np.float32)


def reference_to_rgba_float32(image: FrozenConfigImage) -> np.ndarray:
    """Convert an immutable detector reference to display-ready RGBA.

    Freezing configuration images into Python tuples intentionally discards the
    source numpy dtype. Values already in ``[0, 1]`` are preserved; other
    values use the conventional OpenCV ``[0, 255]`` range and are clipped for
    display. Detector evaluation continues to use the original values.
    """

    array = np.asarray(image, dtype=np.float32)
    if np.min(array) >= 0.0 and np.max(array) <= 1.0:
        normalized = array
    else:
        normalized = np.clip(array, 0.0, 255.0) / 255.0
    return to_rgba_float32(normalized)


def flatten(rgba: np.ndarray) -> np.ndarray:
    """Return a contiguous 1-D view of an RGBA float32 array for upload."""

    return np.ascontiguousarray(rgba, dtype=np.float32).ravel()
