"""Cache-aware evaluation and shared image preprocessing.

``preprocessed`` memoizes image computations on a frame's shared cache so
several detectors and scenario contexts sharing a computation run it once.
``evaluate`` caches one complete ``DetectionResult`` per detector definition,
reusing it across equivalent instances. Exceptions and non-``DetectionResult``
values are never cached.

References inside detector configuration (for example ``MeanAbsoluteSimilarityDetector``)
must be hashable (use tuples) so the detectors stay usable as cache keys.
"""

from collections.abc import Callable

import cv2
import numpy as np

from divergencesplitter.detector.interface import ImageDetector
from divergencesplitter.detector.models import (
    ConfigImage,
    DetectionResult,
    Region,
    freeze_config_image,
)
from divergencesplitter.frame.models import FrameContext, ImageArray

FRAME_MEAN_KEY = "frame-mean"
FRAME_GRAY_KEY = "frame-gray"


def _clamp_unit_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def prepare_reference_alpha(
    reference: np.ndarray,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Remove a reference alpha channel and apply the binary mask contract."""
    source = np.asarray(reference)
    if source.ndim != 3 or source.shape[2] != 4:
        return source, None
    alpha = source[:, :, 3]
    if np.all(alpha == 0):
        raise ValueError("reference alpha mask has no valid pixels")
    if not np.all((alpha == 0) | (alpha == 255)):
        raise ValueError("reference alpha must contain only 0 or 255")
    if np.all(alpha == 255):
        return source[:, :, :3], None
    return source[:, :, :3], np.ascontiguousarray((alpha == 255).astype(np.uint8) * 255)


def preprocessed[T](context: FrameContext, key: object, compute: Callable[[], T]) -> T:
    """Return the value for ``key``, computing and caching it on the first use.

    Cache membership is decided by key presence so ``None`` is a valid cached
    value and is not recomputed. The cache is shared by every ``FrameContext``
    created from the same ``SharedFrameEvaluation``, and concurrent requests for
    the same key run ``compute`` only once.
    """
    return context.cache.preprocessing(key, compute)


def evaluate(context: FrameContext, detector: ImageDetector) -> DetectionResult:
    """Return ``detector``'s result, evaluated at most once per frame.

    Equivalent detectors share the cached result across every context of the
    frame. The result is only cached when it is a complete ``DetectionResult``.
    """

    def compute() -> DetectionResult:
        result = detector.detect(context)
        if not isinstance(result, DetectionResult):
            raise TypeError(
                f"detector returned a non-DetectionResult value: {result!r}"
            )
        return result

    return context.cache.detection(detector, compute)


def frame_mean(context: FrameContext) -> float:
    return frame_mean_region(context, None)


def frame_region(context: FrameContext, region: Region | None) -> ImageArray:
    key = "frame-region" if region is None else ("frame-region", region)
    return preprocessed(context, key, lambda: _region(context.frame.image, region))


def frame_mean_region(context: FrameContext, region: Region | None) -> float:
    key = FRAME_MEAN_KEY if region is None else (FRAME_MEAN_KEY, region)
    return preprocessed(context, key, lambda: _mean(frame_region(context, region)))


def frame_mean_abs_diff(
    context: FrameContext, reference: ConfigImage, region: Region | None = None
) -> float:
    frozen_reference = freeze_config_image(reference)
    key = (
        ("frame-mean-abs-diff", frozen_reference)
        if region is None
        else ("frame-mean-abs-diff", frozen_reference, region)
    )
    return preprocessed(
        context,
        key,
        lambda: _mean_abs_diff(frame_region(context, region), frozen_reference),
    )


def frame_gray(context: FrameContext, region: Region | None = None) -> ImageArray:
    """Return the frame converted to grayscale float32, cached per frame."""
    return preprocessed(
        context,
        FRAME_GRAY_KEY if region is None else (FRAME_GRAY_KEY, region),
        lambda: to_gray(frame_region(context, region)),
    )


def frame_dhash(
    context: FrameContext, hash_size: int, region: Region | None = None
) -> ImageArray:
    """Return the frame's difference-hash bits, cached per frame and hash size."""
    key = (
        ("frame-dhash", hash_size)
        if region is None
        else ("frame-dhash", hash_size, region)
    )
    return preprocessed(
        context, key, lambda: dhash_bits(frame_gray(context, region), hash_size)
    )


def to_gray(image: ImageArray) -> ImageArray:
    """Convert ``image`` to single-channel grayscale float32.

    Two-dimensional single-channel images are passed through. Three-channel
    images are converted with ``cv2.COLOR_BGR2GRAY``.
    """
    source = np.asarray(image)
    if np.issubdtype(source.dtype, np.floating) and not np.all(np.isfinite(source)):
        raise ValueError("image values must be finite")
    array = source.astype(np.float32, copy=False)
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
    right_array, mask = prepare_reference_alpha(np.asarray(right))
    right_array = right_array.astype(np.float64, copy=False)
    if left.shape != right_array.shape:
        raise ValueError(f"shape mismatch: {left.shape} != {right_array.shape}")
    diff = np.abs(left.astype(np.float64) - right_array)
    if mask is not None:
        return float(np.mean(diff[mask != 0]))
    return float(np.mean(diff))


def _region(image: ImageArray, region: Region | None) -> ImageArray:
    if region is None:
        return image
    if (
        region.x + region.width > image.shape[1]
        or region.y + region.height > image.shape[0]
    ):
        raise ValueError(f"region {region} does not fit in image shape {image.shape}")
    return image[
        region.y : region.y + region.height, region.x : region.x + region.width
    ]
