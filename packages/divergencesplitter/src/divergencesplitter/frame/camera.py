"""OpenCV camera frame source.

``OpenCvCameraSource`` captures frames from a camera device opened through
OpenCV. Unlike ``VideoFileSource`` it performs no pacing: the camera delivers
frames at its own rate, so each ``read`` returns the decoded frame provided by
the selected backend.
"""

import math
from dataclasses import dataclass
from types import TracebackType
from typing import Self

import cv2

from divergencesplitter.clock import TimeProvider
from divergencesplitter.frame.models import Frame
from divergencesplitter.frame.normalizer import (
    ClipRegion,
    FrameNormalizer,
    OutputSize,
)
from divergencesplitter.frame.source import (
    ErrorAction,
    FrameSourceError,
    FrameSourceState,
)


@dataclass(frozen=True)
class OpenCvCameraError(FrameSourceError):
    """Base type for all ``OpenCvCameraSource``-specific errors."""

    message: str


class OpenCvCameraOpenError(OpenCvCameraError):
    """The camera device could not be opened."""


class OpenCvCameraConfigurationError(OpenCvCameraError):
    """The camera device rejected the requested capture configuration."""


class OpenCvCameraReadError(OpenCvCameraError):
    """A frame could not be read from the camera device."""


class OpenCvCameraReadBeforeReadyError(OpenCvCameraError):
    """``read`` was attempted while the source is not READY."""


class OpenCvCameraSource:
    """Reads raw frames from an OpenCV-backed camera device."""

    def __init__(
        self,
        device_index: int = 0,
        backend: int = cv2.CAP_ANY,
        width: int | None = None,
        height: int | None = None,
        fps: float | None = None,
        clip_region: ClipRegion | None = None,
        output_size: OutputSize | None = None,
        time_provider: TimeProvider | None = None,
    ) -> None:
        if device_index < 0:
            raise ValueError(f"device_index must be non-negative: {device_index}")
        if (width is None) != (height is None):
            raise ValueError("width and height must be specified together or omitted")
        if width is not None and height is not None and (width <= 0 or height <= 0):
            raise ValueError(f"width and height must be positive: {(width, height)}")
        if fps is not None and (not math.isfinite(fps) or fps <= 0):
            raise ValueError(f"fps must be finite and positive: {fps}")
        self._normalizer = FrameNormalizer(
            clip_region=clip_region, output_size=output_size
        )
        self._device_index = device_index
        self._backend = backend
        self._width = width
        self._height = height
        self._fps = fps
        self._time_provider = (
            time_provider if time_provider is not None else TimeProvider()
        )
        self._capture: cv2.VideoCapture | None = None
        self._state = FrameSourceState.NOT_READY

    @property
    def state(self) -> FrameSourceState:
        return self._state

    @property
    def normalizer(self) -> FrameNormalizer:
        return self._normalizer

    def prepare(self) -> FrameSourceError | None:
        if self._state is FrameSourceState.READY:
            return None
        capture = cv2.VideoCapture(self._device_index, self._backend)
        if not capture.isOpened():
            capture.release()
            self._capture = None
            self._state = FrameSourceState.NOT_READY
            return OpenCvCameraOpenError(
                "cannot open camera device "
                f"{self._device_index!r} with backend {self._backend!r}"
            )
        self._capture = capture
        for prop, value in (
            (cv2.CAP_PROP_FRAME_WIDTH, self._width),
            (cv2.CAP_PROP_FRAME_HEIGHT, self._height),
            (cv2.CAP_PROP_FPS, self._fps),
        ):
            if value is not None and not capture.set(prop, value):
                capture.release()
                self._capture = None
                self._state = FrameSourceState.NOT_READY
                return OpenCvCameraConfigurationError(
                    f"cannot configure camera property {prop} to {value!r}"
                )
        self._state = FrameSourceState.READY
        return None

    def read(self) -> Frame | FrameSourceError:
        if self._state is not FrameSourceState.READY or self._capture is None:
            return OpenCvCameraReadBeforeReadyError("source is not READY")
        retval, image = self._capture.read()
        if not retval or image is None:
            self._capture.release()
            self._capture = None
            self._state = FrameSourceState.NOT_READY
            return OpenCvCameraReadError("failed to read a frame from the camera")
        return Frame(image=image, captured_at=self._time_provider.now())

    def handle_error(self, error: FrameSourceError) -> ErrorAction:
        if isinstance(error, (OpenCvCameraOpenError, OpenCvCameraReadError)):
            return ErrorAction.RETRY
        return ErrorAction.STOP

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        self._state = FrameSourceState.NOT_READY

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
