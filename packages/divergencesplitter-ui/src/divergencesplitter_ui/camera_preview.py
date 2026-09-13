"""Independent camera and NDI preview lifecycle for the Configuration page.

The preview owns a camera source separately from the scenario runtime. This
allows a configured camera to be opened and displayed while scenario fields
are still empty or being edited.
"""

from __future__ import annotations

import threading
from pathlib import Path

from divergencesplitter.frame.camera import CameraCaptureSettings, OpenCvCameraSource
from divergencesplitter.frame.models import Frame
from divergencesplitter.frame.ndi import NdiSource
from divergencesplitter.frame.normalizer import (
    FrameNormalizationError,
    FrameNormalizer,
    ResizeInterpolation,
)
from divergencesplitter.frame.source import ErrorAction, FrameSourceError
from divergencesplitter_runtime.configuration.models import (
    CameraSourceConfiguration,
    NdiSourceConfiguration,
    SourceTransformConfiguration,
)
from divergencesplitter_runtime.configuration.source_builder import (
    build_frame_source,
)


class CameraPreview:
    """Read the latest camera or NDI frame without scenario execution."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: Frame | None = None
        self._source = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._error: str | None = None
        self._normalizer = FrameNormalizer()

    @property
    def error(self) -> str | None:
        with self._lock:
            return self._error

    @property
    def capture_settings(self) -> CameraCaptureSettings | None:
        with self._lock:
            if not isinstance(self._source, OpenCvCameraSource):
                return None
            return self._source.capture_settings

    def start(
        self,
        configuration: CameraSourceConfiguration | NdiSourceConfiguration,
        base_directory: Path,
    ) -> None:
        self.stop()
        source = build_frame_source(configuration, base_directory=base_directory)
        with self._lock:
            self._source = source
            self._latest = None
            self._error = None
            self._normalizer = FrameNormalizer(
                crop_margins=(
                    configuration.transform.crop.to_crop_margins()
                    if configuration.transform.crop is not None
                    else None
                ),
                output_size=(
                    configuration.transform.resize.to_output_size()
                    if configuration.transform.resize is not None
                    else None
                ),
                resize_interpolation=(
                    configuration.transform.resize.interpolation
                    if configuration.transform.resize is not None
                    else ResizeInterpolation.AREA
                ),
            )
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(source,),
            name="camera-preview",
            daemon=True,
        )
        self._thread.start()

    def take_latest(self) -> Frame | None:
        with self._lock:
            frame = self._latest
            self._latest = None
            return frame

    def stop(self) -> None:
        self._stop.set()
        source = self._source
        if source is not None and not isinstance(source, NdiSource):
            source.close()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._lock:
            self._source = None
            self._thread = None
            self._latest = None

    def update_transform(self, transform: SourceTransformConfiguration) -> None:
        """Update preview processing without reopening the capture device."""
        normalizer = FrameNormalizer(
            crop_margins=(
                transform.crop.to_crop_margins() if transform.crop is not None else None
            ),
            output_size=(
                transform.resize.to_output_size()
                if transform.resize is not None
                else None
            ),
            resize_interpolation=(
                transform.resize.interpolation
                if transform.resize is not None
                else ResizeInterpolation.AREA
            ),
        )
        with self._lock:
            self._normalizer = normalizer
            self._error = None

    def _run(self, source) -> None:
        try:
            while not self._stop.is_set():
                error = source.prepare()
                if error is not None:
                    self._set_error(error)
                    if (
                        isinstance(source, NdiSource)
                        and source.handle_error(error) is ErrorAction.RETRY
                    ):
                        self._stop.wait(0.1)
                        continue
                    return
                frame = source.read()
                if frame is None:
                    continue
                if isinstance(frame, FrameSourceError):
                    self._set_error(frame)
                    if (
                        isinstance(source, NdiSource)
                        and source.handle_error(frame) is ErrorAction.RETRY
                    ):
                        self._stop.wait(0.1)
                        continue
                    return
                with self._lock:
                    normalizer = self._normalizer
                frame = normalizer.normalize(frame)
                if isinstance(frame, FrameNormalizationError):
                    self._set_error(frame)
                    continue
                with self._lock:
                    self._error = None
                    self._latest = frame
        except Exception as error:  # noqa: BLE001
            with self._lock:
                self._error = str(error)
        finally:
            source.close()

    def _set_error(self, error: FrameSourceError | FrameNormalizationError) -> None:
        with self._lock:
            self._error = str(error)
