"""Pure sizing helpers for fitting an input frame into the preview region."""

from __future__ import annotations

from dataclasses import dataclass


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
