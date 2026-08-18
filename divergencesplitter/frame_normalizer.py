"""Common clip and resize normalization shared by all frame sources."""

import cv2

from divergencesplitter.models import Frame


class FrameNormalizationError(Exception):
    """Base type for errors returned by ``FrameNormalizer.normalize``."""


class FrameClipError(FrameNormalizationError):
    """A frame does not fully contain the configured clip region."""


class FrameResizeError(FrameNormalizationError):
    """A frame could not be resized to the configured output size."""


class FrameNormalizer:
    """Applies the configured clip and resize to raw frames at evaluation time."""

    def __init__(
        self,
        clip_region: tuple[int, int, int, int] | None = None,
        output_size: tuple[int, int] | None = None,
    ) -> None:
        if clip_region is not None:
            x, y, width, height = clip_region
            if x < 0 or y < 0:
                raise ValueError(f"clip_region must be non-negative: {clip_region}")
            if width <= 0 or height <= 0:
                raise ValueError(
                    f"clip_region must have a positive size: {clip_region}"
                )
        if output_size is not None:
            width, height = output_size
            if width <= 0 or height <= 0:
                raise ValueError(f"output_size must be positive: {output_size}")
        self._clip_region = clip_region
        self._output_size = output_size

    @property
    def clip_region(self) -> tuple[int, int, int, int] | None:
        return self._clip_region

    @property
    def output_size(self) -> tuple[int, int] | None:
        return self._output_size

    def normalize(self, frame: Frame) -> Frame | FrameNormalizationError:
        image = frame.image
        if self._clip_region is not None:
            x, y, width, height = self._clip_region
            if y + height > image.shape[0] or x + width > image.shape[1]:
                return FrameClipError(
                    f"clip region {self._clip_region} does not fit in "
                    f"image shape {image.shape}"
                )
            image = image[y : y + height, x : x + width]
            if self._output_size is None:
                return Frame(image=image.copy())
        if self._output_size is not None:
            try:
                image = cv2.resize(
                    image, self._output_size, interpolation=cv2.INTER_LINEAR
                )
            except cv2.error as error:
                return FrameResizeError(f"failed to resize frame: {error}")
            return Frame(image=image)
        return frame
