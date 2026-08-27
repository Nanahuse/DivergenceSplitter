"""Cache-aware evaluation and shared image preprocessing.

``preprocessed`` memoizes image computations per ``FrameContext`` so several
detectors sharing a computation run it once. ``evaluate`` caches one complete
``DetectionResult`` per detector definition, reusing it across equivalent
instances. Exceptions and non-``DetectionResult`` values are never cached.

References inside detector configuration (for example ``MeanAbsoluteSimilarityDetector``)
must be hashable (use tuples) so the detectors stay usable as cache keys.
"""

from collections.abc import Callable
from typing import cast

import cv2
import numpy as np

from divergencesplitter.detector.interface import ImageDetector
from divergencesplitter.detector.models import (
    ConfigImage,
    DetectionResult,
    freeze_config_image,
)
from divergencesplitter.frame.models import FrameContext, ImageArray

FRAME_MEAN_KEY = "frame-mean"
FRAME_GRAY_KEY = "frame-gray"


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


def frame_mean(context: FrameContext) -> float:
    return preprocessed(context, FRAME_MEAN_KEY, lambda: _mean(context.frame.image))


def frame_mean_abs_diff(context: FrameContext, reference: ConfigImage) -> float:
    frozen_reference = freeze_config_image(reference)
    key = ("frame-mean-abs-diff", frozen_reference)
    return preprocessed(
        context, key, lambda: _mean_abs_diff(context.frame.image, frozen_reference)
    )


def frame_gray(context: FrameContext) -> ImageArray:
    """Return the frame converted to grayscale float32, cached per frame."""
    return preprocessed(context, FRAME_GRAY_KEY, lambda: to_gray(context.frame.image))


def frame_dhash(context: FrameContext, hash_size: int) -> ImageArray:
    """Return the frame's difference-hash bits, cached per frame and hash size."""
    key = ("frame-dhash", hash_size)
    return preprocessed(
        context, key, lambda: dhash_bits(frame_gray(context), hash_size)
    )


def to_gray(image: ImageArray) -> ImageArray:
    """Convert ``image`` to single-channel grayscale float32.

    Two-dimensional single-channel images are passed through. Three-channel
    images are converted with ``cv2.COLOR_BGR2GRAY``.
    """
    array = np.asarray(image, dtype=np.float32)
    if not np.all(np.isfinite(array)):
        raise ValueError("image values must be finite")
    if array.ndim == 2:
        gray = array
    elif array.ndim == 3 and array.shape[2] == 3:
        gray = cv2.cvtColor(array, cv2.COLOR_BGR2GRAY)
    elif array.ndim == 3 and array.shape[2] == 1:
        gray = array[:, :, 0]
    else:
        raise ValueError(f"unsupported image shape for grayscale: {array.shape}")
    return gray.astype(np.float32, copy=False)


def dhash_bits(gray: ImageArray, hash_size: int) -> ImageArray:
    """Compute a difference hash over ``gray``.

    ``gray`` is resized to ``(hash_size + 1, hash_size)`` and each output bit
    encodes whether the left neighbor column is darker. The result is a boolean
    array of shape ``(hash_size, hash_size)``.
    """
    resized = cv2.resize(gray, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    return resized[:, 1:] > resized[:, :-1]


def _mean(image: ImageArray) -> float:
    return float(np.mean(image))


def _mean_abs_diff(left: ImageArray, right: ConfigImage) -> float:
    right_array = np.asarray(right, dtype=np.float64)
    if left.shape != right_array.shape:
        raise ValueError(f"shape mismatch: {left.shape} != {right_array.shape}")
    diff = np.abs(left.astype(np.float64) - right_array)
    return float(np.mean(diff))
