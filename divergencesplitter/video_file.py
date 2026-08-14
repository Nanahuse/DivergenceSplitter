"""Local video file frame source built on OpenCV.

``VideoFileSource`` replays a recording in real time at the frame rate recorded
in the file. It is the test/verification input of the system; camera and NDI
inputs are separate implementations.
"""

import time
from types import TracebackType
from typing import Self

import cv2

from divergencesplitter.frame_source import ErrorAction, FrameSourceState
from divergencesplitter.models import Frame

DEFAULT_FPS = 30.0


class VideoFileError(Exception):
    """Base type for all ``VideoFileSource``-specific errors."""


class VideoFileOpenError(VideoFileError):
    """The video file could not be opened."""


class VideoFileEndOfFileError(VideoFileError):
    """The video file has been fully consumed."""


class VideoFileDecodeError(VideoFileError):
    """A frame could not be decoded from the video stream."""


class VideoFileReadBeforeReadyError(VideoFileError):
    """``read`` was attempted while the source is not READY."""


class VideoFileSource:
    """Replays a local video file paced by ``time.monotonic``.

    The first frame is available as soon as the source is READY; every
    following ``read`` waits until the recorded frame rate's real-time slot.
    A file is opened by ``prepare`` only, so the source may be retried after a
    failed ``prepare``. EOF, open, decode, and read-before-ready conditions are
    returned as source-specific errors, never raised.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._capture: cv2.VideoCapture | None = None
        self._state = FrameSourceState.NOT_READY
        self._fps = DEFAULT_FPS
        self._playback_started = 0.0
        self._frames_read = 0

    @property
    def state(self) -> FrameSourceState:
        return self._state

    def prepare(self) -> VideoFileError | None:
        if self._state is FrameSourceState.READY:
            return None
        capture = cv2.VideoCapture(self._path)
        if not capture.isOpened():
            capture.release()
            self._state = FrameSourceState.NOT_READY
            return VideoFileOpenError(f"cannot open video file: {self._path!r}")
        self._capture = capture
        recorded_fps = capture.get(cv2.CAP_PROP_FPS)
        self._fps = recorded_fps if recorded_fps > 0 else DEFAULT_FPS
        self._playback_started = time.monotonic()
        self._frames_read = 0
        self._state = FrameSourceState.READY
        return None

    def read(self) -> Frame | VideoFileError:
        if self._state is not FrameSourceState.READY or self._capture is None:
            return VideoFileReadBeforeReadyError("source is not READY")
        self._wait_for_slot()
        retval, image = self._capture.read()
        if not retval or image is None:
            return self._classify_failure()
        self._frames_read += 1
        return Frame(image=image)

    def handle_error(self, _error: VideoFileError) -> ErrorAction:
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

    def _wait_for_slot(self) -> None:
        target = self._playback_started + self._frames_read / self._fps
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    def _classify_failure(self) -> VideoFileError:
        assert self._capture is not None
        total = self._capture.get(cv2.CAP_PROP_FRAME_COUNT)
        position = self._capture.get(cv2.CAP_PROP_POS_FRAMES)
        if total <= 0 or position >= total:
            return VideoFileEndOfFileError("reached the end of the video file")
        return VideoFileDecodeError("failed to decode a frame")
