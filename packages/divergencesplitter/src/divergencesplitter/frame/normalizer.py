"""Common clip and resize normalization shared by all frame sources."""

from dataclasses import dataclass
from enum import StrEnum

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
class CropMargins:
    left: int
    right: int
    top: int
    bottom: int

    def __post_init__(self) -> None:
        if min(self.left, self.right, self.top, self.bottom) < 0:
            raise ValueError(f"crop margins must be non-negative: {self}")


@dataclass(frozen=True)
class OutputSize:
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"output size must be positive: {self}")


class ResizeInterpolation(StrEnum):
    AREA = "area"
    NEAREST = "nearest"
    LINEAR = "linear"
    CUBIC = "cubic"
    LANCZOS4 = "lanczos4"


_INTERPOLATION_TO_CV2 = {
    ResizeInterpolation.AREA: cv2.INTER_AREA,
    ResizeInterpolation.NEAREST: cv2.INTER_NEAREST,
    ResizeInterpolation.LINEAR: cv2.INTER_LINEAR,
    ResizeInterpolation.CUBIC: cv2.INTER_CUBIC,
    ResizeInterpolation.LANCZOS4: cv2.INTER_LANCZOS4,
}


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
        crop_margins: CropMargins | None = None,
        output_size: OutputSize | None = None,
        resize_interpolation: ResizeInterpolation = ResizeInterpolation.AREA,
    ) -> None:
        if clip_region is not None and crop_margins is not None:
            raise ValueError("clip_region and crop_margins are mutually exclusive")
        self._clip_region = clip_region
        self._crop_margins = crop_margins
        self._output_size = output_size
        self._resize_interpolation = ResizeInterpolation(resize_interpolation)

    @property
    def clip_region(self) -> ClipRegion | None:
        return self._clip_region

    @property
    def output_size(self) -> OutputSize | None:
        return self._output_size

    @property
    def crop_margins(self) -> CropMargins | None:
        return self._crop_margins

    @property
    def resize_interpolation(self) -> ResizeInterpolation:
        return self._resize_interpolation

    def normalize(self, frame: Frame) -> Frame | FrameNormalizationError:
        image = frame.image
        region = self._clip_region
        if self._crop_margins is not None:
            margins = self._crop_margins
            if (
                margins.left + margins.right >= image.shape[1]
                or margins.top + margins.bottom >= image.shape[0]
            ):
                return FrameClipError(
                    f"crop margins {margins} do not fit in image shape {image.shape}"
                )
            region = ClipRegion(
                margins.left,
                margins.top,
                image.shape[1] - margins.left - margins.right,
                image.shape[0] - margins.top - margins.bottom,
            )
        if region is not None:
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
                    interpolation=_INTERPOLATION_TO_CV2[self._resize_interpolation],
                )
            except cv2.error as error:
                return FrameResizeError(f"failed to resize frame: {error}")
            return Frame(image=image, captured_at=frame.captured_at)
        return frame
