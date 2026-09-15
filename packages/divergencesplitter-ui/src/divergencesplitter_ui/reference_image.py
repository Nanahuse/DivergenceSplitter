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

from divergencesplitter_ui.image import reference_to_rgba_float32


def reference_to_png_bytes(image: FrozenConfigImage) -> bytes:
    """Encode one reference image as PNG bytes for ``flet.Image``.

    The frozen image is normalized to RGBA the same way the Dear PyGui texture
    path does, then encoded losslessly. Raises ``ValueError`` when OpenCV cannot
    encode the result.
    """

    rgba = reference_to_rgba_float32(image)
    rgba_uint8 = np.clip(rgba * 255.0, 0.0, 255.0).astype(np.uint8)
    bgra = np.ascontiguousarray(rgba_uint8[:, :, [2, 1, 0, 3]])
    success, buffer = cv2.imencode(".png", bgra)
    if not success:
        raise ValueError("could not encode the reference image as PNG")
    return bytes(buffer)
