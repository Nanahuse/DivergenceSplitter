"""Detector configuration and result data models.

Detector configuration values remain hashable so equivalent detectors can
share cache entries.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import numpy as np

Pixel = int | float
ConfigImage = Sequence[Sequence[Pixel]] | Sequence[Sequence[Sequence[Pixel]]]
FrozenConfigImage = (
    tuple[tuple[Pixel, ...], ...] | tuple[tuple[tuple[Pixel, ...], ...], ...]
)


@dataclass(frozen=True)
class DetectionResult:
    """Data model holding the numeric observation of a single detector run.

    ``score`` is a required detector-specific measure with no cross-detector
    meaning.
    """

    score: float


@dataclass(frozen=True)
class MeanAbsoluteSimilarityConfig:
    """Configuration for mean absolute similarity detection."""

    reference: FrozenConfigImage

    def __post_init__(self) -> None:
        _validate_frozen_config_image(self.reference)


@dataclass(frozen=True)
class TemplateMatchConfig:
    """Configuration for normalized template matching."""

    reference: FrozenConfigImage

    def __post_init__(self) -> None:
        _validate_frozen_config_image(self.reference)
        template = np.asarray(self.reference, dtype=np.float32)
        if np.all(np.ptp(template, axis=(0, 1)) == 0):
            raise ValueError("template must contain spatial variation")


@dataclass(frozen=True)
class ColorRangeConfig:
    """Inclusive color bounds used by color-range detection."""

    lower: tuple[Pixel, ...]
    upper: tuple[Pixel, ...]

    def __post_init__(self) -> None:
        lower = freeze_pixel_vector(self.lower)
        upper = freeze_pixel_vector(self.upper)
        if type(self.lower) is not tuple or type(self.upper) is not tuple:
            raise ValueError("color bounds must be tuples")
        if len(lower) not in (1, 3):
            raise ValueError(f"color bound length must be 1 or 3, got {len(lower)}")
        if len(lower) != len(upper):
            raise ValueError(
                f"color bound length mismatch: {len(lower)} != {len(upper)}"
            )
        for lo, hi in zip(lower, upper):
            if lo > hi:
                raise ValueError(f"lower bound exceeds upper bound: {lower} > {upper}")


@dataclass(frozen=True)
class PhaseCorrelationConfig:
    """Configuration for phase-correlation detection."""

    reference: FrozenConfigImage

    def __post_init__(self) -> None:
        _validate_frozen_config_image(self.reference)


@dataclass(frozen=True)
class DifferenceHashSimilarityConfig:
    """Configuration for difference-hash similarity detection."""

    reference: FrozenConfigImage
    hash_size: int = 8

    def __post_init__(self) -> None:
        _validate_frozen_config_image(self.reference)
        if type(self.hash_size) is not int or self.hash_size <= 0:
            raise ValueError(
                f"hash_size must be a positive integer: {self.hash_size!r}"
            )


def freeze_config_image(image: ConfigImage) -> FrozenConfigImage:
    """Validate ``image`` and freeze it into nested tuples.

    The image must be non-empty, rectangular, and contain only finite numeric
    values. Nested sequences are converted to tuples so the result is hashable.
    """
    if len(image) == 0:
        raise ValueError("image config must not be empty")
    first = image[0]
    if type(first) is int or type(first) is float:
        raise ValueError("image rows must be sequences")
    if len(first) == 0:
        raise ValueError("image rows must not be empty")
    if isinstance(first[0], Sequence):
        return _freeze_3d(cast("Sequence[Sequence[Sequence[Pixel]]]", image))
    return _freeze_2d(cast("Sequence[Sequence[Pixel]]", image))


def freeze_pixel_vector(values: Sequence[Pixel]) -> tuple[Pixel, ...]:
    """Validate and freeze a flat sequence of pixel values into a tuple."""
    frozen = tuple(_freeze_pixel(value) for value in values)
    if len(frozen) == 0:
        raise ValueError("pixel vector must not be empty")
    return frozen


def _validate_frozen_config_image(image: FrozenConfigImage) -> None:
    """Validate an image and require its complete structure to use tuples."""
    freeze_config_image(image)
    if not _contains_only_tuples(image):
        raise ValueError("reference image must use nested tuples")


def _contains_only_tuples(value: object) -> bool:
    if type(value) is not tuple:
        return False
    return all(
        type(item) is int or type(item) is float or _contains_only_tuples(item)
        for item in value
    )


def _freeze_2d(image: Sequence[Sequence[Pixel]]) -> tuple[tuple[Pixel, ...], ...]:
    if len(image) == 0:
        raise ValueError("image config must not be empty")
    width: int | None = None
    rows: list[tuple[Pixel, ...]] = []
    for row in image:
        frozen = _freeze_row(row)
        if width is None:
            width = len(frozen)
        elif len(frozen) != width:
            raise ValueError("image config must be rectangular")
        rows.append(frozen)
    return tuple(rows)


def _freeze_3d(
    image: Sequence[Sequence[Sequence[Pixel]]],
) -> tuple[tuple[tuple[Pixel, ...], ...], ...]:
    planes = tuple(_freeze_2d(plane) for plane in image)
    height, width = len(planes[0]), len(planes[0][0])
    for plane in planes[1:]:
        if (len(plane), len(plane[0])) != (height, width):
            raise ValueError("image config must be rectangular")
    return planes


def _freeze_row(row: Sequence[Pixel]) -> tuple[Pixel, ...]:
    frozen = tuple(_freeze_pixel(value) for value in row)
    if len(frozen) == 0:
        raise ValueError("image rows must not be empty")
    return frozen


def _freeze_pixel(value: Pixel) -> Pixel:
    if type(value) is not int and type(value) is not float:
        raise ValueError(f"image values must be numbers: {value!r}")
    if type(value) is float and not math.isfinite(value):
        raise ValueError(f"image values must be finite: {value!r}")
    return value
