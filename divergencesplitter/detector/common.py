"""Cache-aware evaluation and shared image preprocessing.

``preprocessed`` memoizes image computations per ``FrameContext`` so several
detectors sharing a computation run it once. ``evaluate`` caches complete
``DetectionSample`` results per detector instance, reusing them across
equivalent definitions. Exceptions and non-``DetectionSample`` returns are
never cached.

References inside detector configuration (for example ``FrameDifferenceDetector``)
must be hashable (use tuples) so the detectors stay usable as cache keys.
"""

from collections.abc import Callable
from typing import cast

import numpy as np

from divergencesplitter.detector.interface import ImageDetector
from divergencesplitter.models import (
    ConfigImage,
    DetectionSample,
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


def evaluate(context: FrameContext, detector: ImageDetector) -> DetectionSample:
    """Return ``detector``'s sample, evaluated at most once per frame.

    Equivalent detectors share the cached sample within one ``FrameContext``.
    The result is only cached when it is a complete ``DetectionSample``.
    """
    cached = context.detection_cache.get(detector)
    if isinstance(cached, DetectionSample):
        return cached
    sample = detector.detect(context)
    if not isinstance(sample, DetectionSample):
        raise TypeError(f"detector returned a non-DetectionSample result: {sample!r}")
    context.detection_cache[detector] = sample
    return sample


def frame_mean(context: FrameContext) -> float:
    return preprocessed(context, FRAME_MEAN_KEY, lambda: _mean(context.frame.image))


def frame_mean_abs_diff(context: FrameContext, reference: ConfigImage) -> float:
    key = ("frame-mean-abs-diff", reference)
    return preprocessed(
        context, key, lambda: _mean_abs_diff(context.frame.image, reference)
    )


def _mean(image: ImageArray) -> float:
    return float(np.mean(image))


def _mean_abs_diff(left: ImageArray, right: ConfigImage) -> float:
    right_array = np.asarray(right, dtype=np.float64)
    if left.shape != right_array.shape:
        raise ValueError(f"shape mismatch: {left.shape} != {right_array.shape}")
    diff = np.abs(left.astype(np.float64) - right_array)
    return float(np.mean(diff))
