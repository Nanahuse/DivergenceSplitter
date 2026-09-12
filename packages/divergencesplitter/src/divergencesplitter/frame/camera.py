"""OpenCV camera frame source.

``OpenCvCameraSource`` captures frames from a camera device opened through
OpenCV. Unlike ``VideoFileSource`` it performs no pacing: the camera delivers
frames at its own rate, so each ``read`` returns the decoded frame provided by
the selected backend.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Self

import cv2

from divergencesplitter.clock import TimeProvider
from divergencesplitter.frame.models import Frame
from divergencesplitter.frame.normalizer import (
    ClipRegion,
    CropMargins,
    FrameNormalizer,
    OutputSize,
    ResizeInterpolation,
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


@dataclass(frozen=True)
class CameraCaptureSettings:
    """Capture settings reported by OpenCV after opening a camera."""

    width: int
    height: int
    fps: float


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
        crop_margins: CropMargins | None = None,
        output_size: OutputSize | None = None,
        resize_interpolation: ResizeInterpolation = ResizeInterpolation.AREA,
        time_provider: TimeProvider | None = None,
        capture_factory: Callable[[], cv2.VideoCapture | None] | None = None,
        request_60_fps: bool = False,
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
            clip_region=clip_region,
            crop_margins=crop_margins,
            output_size=output_size,
            resize_interpolation=resize_interpolation,
        )
        self._device_index = device_index
        self._backend = backend
        self._width = width
        self._height = height
        self._fps = fps
        self._time_provider = (
            time_provider if time_provider is not None else TimeProvider()
        )
        self._capture_factory = capture_factory
        self._request_60_fps = request_60_fps
        self._capture: cv2.VideoCapture | None = None
        self._capture_settings: CameraCaptureSettings | None = None
        self._state = FrameSourceState.NOT_READY

    @property
    def state(self) -> FrameSourceState:
        return self._state

    @property
    def device_index(self) -> int:
        return self._device_index

    @property
    def backend(self) -> int:
        return self._backend

    @property
    def width(self) -> int | None:
        return self._width

    @property
    def height(self) -> int | None:
        return self._height

    @property
    def fps(self) -> float | None:
        return self._fps

    @property
    def capture_settings(self) -> CameraCaptureSettings | None:
        return self._capture_settings

    @property
    def normalizer(self) -> FrameNormalizer:
        return self._normalizer

    def prepare(self) -> FrameSourceError | None:
        if self._state is FrameSourceState.READY:
            return None
        if self._capture_factory is not None:
            capture = self._capture_factory()
        else:
            capture = cv2.VideoCapture(self._device_index, self._backend)
        if capture is None:
            self._capture = None
            self._capture_settings = None
            self._state = FrameSourceState.NOT_READY
            return OpenCvCameraOpenError("cannot open camera capture")
        if not capture.isOpened():
            capture.release()
            self._capture = None
            self._capture_settings = None
            self._state = FrameSourceState.NOT_READY
            return OpenCvCameraOpenError(
                "cannot open camera device "
                f"{self._device_index!r} with backend {self._backend!r}"
            )
        self._capture = capture
        if self._capture_factory is None:
            for prop, value in (
                (cv2.CAP_PROP_FRAME_WIDTH, self._width),
                (cv2.CAP_PROP_FRAME_HEIGHT, self._height),
                (cv2.CAP_PROP_FPS, self._fps),
            ):
                if value is not None and not capture.set(prop, value):
                    capture.release()
                    self._capture = None
                    self._capture_settings = None
                    self._state = FrameSourceState.NOT_READY
                    return OpenCvCameraConfigurationError(
                        f"cannot configure camera property {prop} to {value!r}"
                    )
        if self._request_60_fps:
            capture.set(cv2.CAP_PROP_FPS, 60.0)
        self._capture_settings = CameraCaptureSettings(
            width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            fps=capture.get(cv2.CAP_PROP_FPS),
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
            self._capture_settings = None
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
            self._capture_settings = None
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
