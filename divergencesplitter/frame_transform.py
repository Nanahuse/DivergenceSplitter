"""Frame cropping and resizing transform.

``FrameCropResize`` clips a rectangular region out of a frame image and
resizes it to a target size. It is an independent component that returns a
new ``Frame`` and never mutates or aliases the input image.
"""

from dataclasses import dataclass

import cv2

from divergencesplitter.models import Frame


@dataclass(frozen=True)
class FrameCropResize:
    """Crop ``frame.image`` to ``region`` and resize it to ``size``.

    ``region`` is ``(x, y, width, height)`` where ``x`` is the column and
    ``y`` is the row. The region end is exclusive like a NumPy slice, so
    ``apply`` clips ``image[y:y+height, x:x+width]`` first and then resizes
    the crop to ``size`` with ``cv2.INTER_LINEAR``.
    """

    region: tuple[int, int, int, int]
    size: tuple[int, int]

    def __post_init__(self) -> None:
        x, y, width, height = self.region
        out_width, out_height = self.size
        if x < 0 or y < 0:
            raise ValueError(f"region must be non-negative: {self.region}")
        if width <= 0 or height <= 0:
            raise ValueError(f"region must have a positive size: {self.region}")
        if out_width <= 0 or out_height <= 0:
            raise ValueError(f"size must be positive: {self.size}")

    def apply(self, frame: Frame) -> Frame:
        x, y, width, height = self.region
        if frame.image.ndim < 2:
            raise ValueError(
                f"image must have at least height and width: ndim={frame.image.ndim}"
            )
        if frame.image.shape[0] < y + height or frame.image.shape[1] < x + width:
            raise ValueError(
                f"region {self.region} does not fit in image shape {frame.image.shape}"
            )
        cropped = frame.image[y : y + height, x : x + width]
        resized = cv2.resize(cropped, self.size, interpolation=cv2.INTER_LINEAR)
        return Frame(image=resized)
