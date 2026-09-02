"""Common clip and resize normalization shared by all frame sources."""

from dataclasses import dataclass

import cv2

from divergencesplitter.frame.models import Frame


@dataclass(frozen=True)
class ClipRegion:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.x < 0 or self.y < 0:
            raise ValueError(f"clip region must be non-negative: {self}")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"clip region must have a positive size: {self}")


@dataclass(frozen=True)
class OutputSize:
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"output size must be positive: {self}")


@dataclass(frozen=True)
class FrameNormalizationError:
    """Base type for errors returned by ``FrameNormalizer.normalize``."""

    message: str


class FrameClipError(FrameNormalizationError):
    """A frame does not fully contain the configured clip region."""


class FrameResizeError(FrameNormalizationError):
    """A frame could not be resized to the configured output size."""


class FrameNormalizer:
    """Applies the configured clip and resize to raw frames at evaluation time."""

    def __init__(
        self,
        clip_region: ClipRegion | None = None,
        output_size: OutputSize | None = None,
    ) -> None:
        self._clip_region = clip_region
        self._output_size = output_size

    @property
    def clip_region(self) -> ClipRegion | None:
        return self._clip_region

    @property
    def output_size(self) -> OutputSize | None:
        return self._output_size

    def normalize(self, frame: Frame) -> Frame | FrameNormalizationError:
        image = frame.image
        if self._clip_region is not None:
            region = self._clip_region
            if (
                region.y + region.height > image.shape[0]
                or region.x + region.width > image.shape[1]
            ):
                return FrameClipError(
                    f"clip region {self._clip_region} does not fit in "
                    f"image shape {image.shape}"
                )
            image = image[
                region.y : region.y + region.height,
                region.x : region.x + region.width,
            ]
            if self._output_size is None:
                return Frame(image=image.copy(), captured_at=frame.captured_at)
        if self._output_size is not None:
            try:
                image = cv2.resize(
                    image,
                    (self._output_size.width, self._output_size.height),
                    interpolation=cv2.INTER_LINEAR,
                )
            except cv2.error as error:
                return FrameResizeError(f"failed to resize frame: {error}")
            return Frame(image=image, captured_at=frame.captured_at)
        return frame
