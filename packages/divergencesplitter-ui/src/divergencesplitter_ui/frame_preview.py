"""Pure sizing and pixel preparation for the input preview region.

Nothing in this module imports a GUI framework, so the pixel work can be
exercised in tests that run without a GPU or a window. :func:`fit_preview` is
the Dear PyGui path, which fits an image into the region measured by the
renderer. :func:`preview_size` and :func:`prepare_preview` are the Flet path:
they bound the preview to a fixed maximum while never upscaling, and return the
downscaled, channel-swapped ``uint8`` array that ``flet.RawImage.render``
requires.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

MAX_PREVIEW_WIDTH = 520
MAX_PREVIEW_HEIGHT = 216


@dataclass(frozen=True)
class PreviewSize:
    width: int
    height: int
    scale: float


def fit_preview(
    frame_width: int,
    frame_height: int,
    available_width: int,
    available_height: int,
) -> PreviewSize:
    if min(frame_width, frame_height, available_width, available_height) <= 0:
        return PreviewSize(0, 0, 0.0)
    scale = min(available_width / frame_width, available_height / frame_height)
    return PreviewSize(
        max(1, round(frame_width * scale)),
        max(1, round(frame_height * scale)),
        scale,
    )


def preview_size(
    frame_width: int,
    frame_height: int,
    *,
    max_width: int = MAX_PREVIEW_WIDTH,
    max_height: int = MAX_PREVIEW_HEIGHT,
) -> PreviewSize:
    """Fit a frame into the preview maximum, preserving aspect ratio.

    Unlike :func:`fit_preview`, the scale is capped at ``1.0`` so a frame
    smaller than the maximum is never upscaled, and both maximum dimensions are
    respected independently so an extreme aspect ratio is still bounded.
    """

    if min(frame_width, frame_height, max_width, max_height) <= 0:
        return PreviewSize(0, 0, 0.0)
    scale = min(
        1.0,
        max_width / frame_width,
        max_height / frame_height,
    )
    return PreviewSize(
        max(1, round(frame_width * scale)),
        max(1, round(frame_height * scale)),
        scale,
    )


def to_rgb_uint8(image: np.ndarray) -> np.ndarray:
    """Return ``image`` as a contiguous RGB ``uint8`` array.

    Accepts the layouts produced by the runtime's frame sources: two-dimensional
    grayscale, singleton-channel, three-channel BGR, and four-channel BGRA. The
    source array is never modified.
    """

    array = np.asarray(image)
    if array.ndim == 2:
        rgb = cv2.cvtColor(array, cv2.COLOR_GRAY2RGB)
    elif array.ndim == 3 and array.shape[2] == 1:
        rgb = cv2.cvtColor(array[:, :, 0], cv2.COLOR_GRAY2RGB)
    elif array.ndim == 3 and array.shape[2] == 3:
        rgb = array[:, :, ::-1]
    elif array.ndim == 3 and array.shape[2] == 4:
        rgb = array[:, :, 2::-1]
    else:
        raise ValueError(f"unsupported image shape: {array.shape}")
    return np.ascontiguousarray(rgb, dtype=np.uint8)


def prepare_preview(
    image: np.ndarray,
    *,
    max_width: int = MAX_PREVIEW_WIDTH,
    max_height: int = MAX_PREVIEW_HEIGHT,
) -> np.ndarray:
    """Prepare one frame for a ``flet.RawImage`` without touching the source.

    The preview-only copy is resized with area interpolation and returned as a
    contiguous RGB ``uint8`` array. The original frame, its dtype, and its
    channel order are left intact.
    """

    array = np.asarray(image)
    size = preview_size(
        int(array.shape[1]),
        int(array.shape[0]),
        max_width=max_width,
        max_height=max_height,
    )
    if size.width == 0 or size.height == 0:
        raise ValueError(f"empty frame: {array.shape}")
    if (size.width, size.height) != (array.shape[1], array.shape[0]):
        array = cv2.resize(
            array,
            (size.width, size.height),
            interpolation=cv2.INTER_AREA,
        )
    return to_rgb_uint8(array)
