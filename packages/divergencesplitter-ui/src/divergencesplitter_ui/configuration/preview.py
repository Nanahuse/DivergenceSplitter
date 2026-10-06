"""Configuration preview lifecycle and Flet ``RawImage`` rendering.

``PreviewController`` owns the independent draft camera/NDI preview and picks
between the runtime's raw input frame (while a session is running) and the
draft capture (while it is not). ``ConfigurationPreview`` is the Flet control:
it renders the newest frame to a ``RawImage`` and never queues frames. Nothing
here changes the frames the runtime evaluates.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft
from divergencesplitter.frame.camera import CameraCaptureSettings
from divergencesplitter.frame.models import Frame
from divergencesplitter.frame.normalizer import FrameNormalizationError
from divergencesplitter_runtime.configuration.models import (
    CameraSourceConfiguration,
    NdiSourceConfiguration,
    SourceTransformConfiguration,
)

from divergencesplitter_ui.camera_preview import CameraPreview
from divergencesplitter_ui.frame_preview import prepare_preview

PREVIEW_MAX_WIDTH = 480
PREVIEW_MAX_HEIGHT = 270


def capture_settings_label(settings: CameraCaptureSettings | None) -> str:
    """Format the actually opened camera, or ``—`` when there is none."""

    if settings is None:
        return "Opened camera: —"
    return f"Opened camera: {settings.width}×{settings.height} @ {settings.fps:.2f} FPS"


def _no_frame() -> Frame | None:
    return None


def _not_active() -> bool:
    return False


class PreviewController:
    """Own the draft preview and normalize whichever frame source is current."""

    def __init__(
        self,
        *,
        camera_preview: CameraPreview | None = None,
        runtime_frame_provider: Callable[[], Frame | None] | None = None,
        runtime_active: Callable[[], bool] | None = None,
    ) -> None:
        self._camera_preview = (
            camera_preview if camera_preview is not None else CameraPreview()
        )
        self._runtime_frame_provider = (
            runtime_frame_provider if runtime_frame_provider is not None else _no_frame
        )
        self._runtime_active = (
            runtime_active if runtime_active is not None else _not_active
        )

    @property
    def error(self) -> str | None:
        return self._camera_preview.error

    @property
    def capture_settings(self) -> CameraCaptureSettings | None:
        return self._camera_preview.capture_settings

    def start_draft(
        self,
        configuration: CameraSourceConfiguration | NdiSourceConfiguration,
    ) -> None:
        self._camera_preview.start(configuration)

    def stop(self) -> None:
        self._camera_preview.stop()

    def update_transform(self, transform: SourceTransformConfiguration) -> None:
        self._camera_preview.update_transform(transform)

    def take_frame(self) -> Frame | None:
        """Return the newest frame for the current mode, or ``None``."""

        if self._runtime_active():
            return self._runtime_frame_provider()
        return self._camera_preview.take_latest()

    def normalize(self, frame: Frame) -> Frame | FrameNormalizationError:
        return self._camera_preview.normalize_frame(frame)


class ConfigurationPreview:
    """Render the newest draft or runtime frame to a ``RawImage``."""

    def __init__(self) -> None:
        self._image = ft.RawImage(
            width=PREVIEW_MAX_WIDTH,
            height=PREVIEW_MAX_HEIGHT,
            fit=ft.BoxFit.CONTAIN,
        )
        self._status = ft.Text("")
        self._control = ft.Column(
            controls=[ft.Text("Input preview"), self._image, self._status],
            spacing=4,
        )

    @property
    def control(self) -> ft.Control:
        return self._control

    async def pump(self, controller: PreviewController) -> bool:
        """Render one frame; return whether the status text changed."""

        frame = controller.take_frame()
        if frame is None:
            return False
        normalized = controller.normalize(frame)
        changed = False
        if isinstance(normalized, FrameNormalizationError):
            message = str(normalized)
            if self._status.value != message:
                self._status.value = message
                changed = True
            return changed
        if self._status.value:
            self._status.value = ""
            changed = True
        try:
            await self._image.render(
                prepare_preview(
                    normalized.image,
                    max_width=PREVIEW_MAX_WIDTH,
                    max_height=PREVIEW_MAX_HEIGHT,
                ),
                premultiplied=True,
            )
        except RuntimeError, TimeoutError:
            return changed
        return changed
