"""Shared detector result models, type aliases, and configuration helpers.

Configuration values remain hashable so equivalent detectors can share cache
entries.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

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


def freeze_config_image(image: ConfigImage) -> FrozenConfigImage:
    """Validate ``image`` and freeze it into nested tuples.

    The image must be non-empty, rectangular, and contain only finite numeric
    values. Nested sequences are converted to tuples so the result is hashable.
    """
    if len(image) == 0:
        raise ValueError("image config must not be empty")
    first = image[0]
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
    """Validate the semantic constraints of a frozen configuration image."""
    freeze_config_image(image)


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
    if not math.isfinite(value):
        raise ValueError(f"image values must be finite: {value!r}")
    return value
