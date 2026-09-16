"""Pure conversion of detector reference images to displayable PNG bytes.

Reference images are static and shown only when the user expands a detector, so
this path is deliberately separate from the high-frequency Input Preview
conversion. Nothing here imports a GUI framework; the Flet Diagnostics control
only hands the resulting bytes to ``flet.Image``.
"""

from __future__ import annotations

import cv2
import numpy as np
from divergencesplitter.detector.models import FrozenConfigImage


def reference_to_rgba_uint8(image: FrozenConfigImage) -> np.ndarray:
    """Normalize one frozen reference image to display-ready RGBA ``uint8``.

    Values already in ``[0, 1]`` are preserved; other values use the
    conventional OpenCV ``[0, 255]`` range. Three- and four-channel inputs are
    treated as OpenCV BGR/BGRA and reversed to RGB(A) for display.
    """

    array = np.asarray(image, dtype=np.float32)
    if np.min(array) >= 0.0 and np.max(array) <= 1.0:
        normalized = array
    else:
        normalized = np.clip(array, 0.0, 255.0) / 255.0
    if normalized.ndim == 2:
        rgb = np.stack((normalized,) * 3, axis=-1)
        alpha = None
    elif normalized.ndim == 3 and normalized.shape[2] == 1:
        gray = normalized[:, :, 0]
        rgb = np.stack((gray,) * 3, axis=-1)
        alpha = None
    elif normalized.ndim == 3 and normalized.shape[2] == 3:
        rgb = normalized[:, :, ::-1]
        alpha = None
    elif normalized.ndim == 3 and normalized.shape[2] == 4:
        rgb = normalized[:, :, 2::-1]
        alpha = normalized[:, :, 3]
    else:
        raise ValueError(f"unsupported reference image shape: {normalized.shape}")
    rgba = np.empty((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
    rgba[:, :, :3] = np.clip(rgb * 255.0, 0.0, 255.0).astype(np.uint8)
    rgba[:, :, 3] = (
        255 if alpha is None else np.clip(alpha * 255.0, 0.0, 255.0).astype(np.uint8)
    )
    return rgba


def reference_to_png_bytes(image: FrozenConfigImage) -> bytes:
    """Encode one reference image as PNG bytes for ``flet.Image``.

    The image is normalized to RGBA the same way the previous texture path did,
    then encoded losslessly. Raises ``ValueError`` when OpenCV cannot encode the
    result.
    """

    rgba = reference_to_rgba_uint8(image)
    bgra = np.ascontiguousarray(rgba[:, :, [2, 1, 0, 3]])
    success, buffer = cv2.imencode(".png", bgra)
    if not success:
        raise ValueError("could not encode the reference image as PNG")
    return bytes(buffer)
