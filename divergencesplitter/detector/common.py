"""Cache-aware evaluation and shared image preprocessing.

``preprocessed`` memoizes image computations per ``FrameContext`` so several
detectors sharing a computation run it once. ``evaluate`` caches one complete
``DetectionResult`` per detector definition, reusing it across equivalent
instances. Exceptions and non-``DetectionResult`` values are never cached.

References inside detector configuration (for example ``FrameDifferenceDetector``)
must be hashable (use tuples) so the detectors stay usable as cache keys.
"""

from collections.abc import Callable
from typing import cast

import cv2
import numpy as np

from divergencesplitter.detector.interface import ImageDetector
from divergencesplitter.models import (
    ConfigImage,
    DetectionResult,
    FrameContext,
    ImageArray,
)

FRAME_MEAN_KEY = "frame-mean"


def preprocessed[T](context: FrameContext, key: object, compute: Callable[[], T]) -> T:
    """Return the value for ``key``, computing and caching it on the first use.

    Cache membership is decided by key presence so ``None`` is a valid cached
    value and is not recomputed.
    """
    if key in context.preprocessing_cache:
        return cast(T, context.preprocessing_cache[key])
    value = compute()
    context.preprocessing_cache[key] = value
    return value


def evaluate(context: FrameContext, detector: ImageDetector) -> DetectionResult:
    """Return ``detector``'s result, evaluated at most once per frame.

    Equivalent detectors share the cached result within one ``FrameContext``.
    The result is only cached when it is a complete ``DetectionResult``.
    """
    cached = context.detection_cache.get(detector)
    if isinstance(cached, DetectionResult):
        return cached
    result = detector.detect(context)
    if not isinstance(result, DetectionResult):
        raise TypeError(f"detector returned a non-DetectionResult value: {result!r}")
    context.detection_cache[detector] = result
    return result


def _resized(context: FrameContext, size: tuple[int, int]) -> ImageArray:
    """Return the frame resized to ``size``, cached per ``FrameContext``.

    The ``(width, height)`` size follows OpenCV's convention. The resized
    array is stored under ``("frame-resize", size)`` so detectors sharing a
    size within one ``FrameContext`` reuse the same array.
    """
    return preprocessed(
        context,
        ("frame-resize", size),
        lambda: cv2.resize(context.frame.image, size, interpolation=cv2.INTER_LINEAR),
    )


def frame_mean(context: FrameContext, size: tuple[int, int] | None = None) -> float:
    image = context.frame.image if size is None else _resized(context, size)
    key = FRAME_MEAN_KEY if size is None else ("frame-mean", size)
    return preprocessed(context, key, lambda: _mean(image))


def frame_mean_abs_diff(
    context: FrameContext,
    reference: ConfigImage,
    size: tuple[int, int] | None = None,
) -> float:
    image = context.frame.image if size is None else _resized(context, size)
    key = (
        ("frame-mean-abs-diff", reference)
        if size is None
        else ("frame-mean-abs-diff", size, reference)
    )
    return preprocessed(context, key, lambda: _mean_abs_diff(image, reference))


def _mean(image: ImageArray) -> float:
    return float(np.mean(image))


def _mean_abs_diff(left: ImageArray, right: ConfigImage) -> float:
    right_array = np.asarray(right, dtype=np.float64)
    if left.shape != right_array.shape:
        raise ValueError(f"shape mismatch: {left.shape} != {right_array.shape}")
    diff = np.abs(left.astype(np.float64) - right_array)
    return float(np.mean(diff))
