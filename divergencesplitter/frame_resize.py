"""Scenario-owned frame resize.

``resize_frame`` is the single place a Scenario applies its size setting. It
is intentionally decoupled from Detector configuration and from any cache.

Call order: Source returns a clipped ``Frame`` (``clip_region`` lives on the
Source side), the Scenario calls ``resize_frame`` once, builds a
``FrameContext`` from the resized ``Frame``, and every Detector evaluates the
same context.
"""

import cv2
import numpy as np

from divergencesplitter.models import Frame


def resize_frame(frame: Frame, size: tuple[int, int]) -> Frame:
    """Resize ``frame.image`` to ``size`` once and return a new ``Frame``.

    ``size`` is ``(width, height)`` in OpenCV order. The input ``frame`` and
    its image are left unchanged; the returned image owns its data and shares
    no memory with the input. Neither this function nor
    ``FrameContext.preprocessing_cache`` caches the result.
    """
    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError(f"size must be positive: {size}")
    image = frame.image
    if not isinstance(image, np.ndarray):
        raise ValueError("frame.image must be a NumPy ndarray")  # noqa: TRY004
    if image.ndim < 2 or image.shape[0] == 0 or image.shape[1] == 0:
        raise ValueError(
            f"frame.image must be a non-empty array with height and width: "
            f"{image.shape}"
        )
    resized = cv2.resize(image, size, interpolation=cv2.INTER_LINEAR)
    return Frame(image=resized)
