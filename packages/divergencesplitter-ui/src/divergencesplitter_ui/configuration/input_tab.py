"""Input tab for the Flet Configuration page.

The tab groups everything that belongs to ``Profile.source``: the input source,
the Configuration preview, and frame processing. It composes the existing
``SourceSection``, ``ConfigurationPreview``, and ``FrameProcessingSection``
instead of re-implementing their logic. When no Profile is selected it shows an
empty state rather than a wall of disabled controls.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft
from divergencesplitter.frame.camera import CameraCaptureSettings

from divergencesplitter_ui.configuration.dialogs import FileDialogs
from divergencesplitter_ui.configuration.frame_processing import FrameProcessingSection
from divergencesplitter_ui.configuration.preview import (
    ConfigurationPreview,
    capture_settings_label,
)
from divergencesplitter_ui.configuration.source import SourceSection
from divergencesplitter_ui.ndi_discovery import NdiDiscovery
from divergencesplitter_ui.settings import (
    EditableProfile,
    EditPermission,
    SettingsModel,
)

_EMPTY_MESSAGE = "Create or open a Profile to configure the input source."


class InputTab:
    """Compose source, preview, and frame processing for the Input tab."""

    def __init__(
        self,
        model: SettingsModel,
        dialogs: FileDialogs,
        *,
        on_input_changed: Callable[[], None],
        on_changed: Callable[[], None],
        preview: ConfigurationPreview,
        ndi_discovery: NdiDiscovery | None = None,
    ) -> None:
        self.source = SourceSection(
            model,
            dialogs,
            on_input_changed=on_input_changed,
            ndi_discovery=ndi_discovery,
        )
        self.preview = preview
        self.frame_processing = FrameProcessingSection(model, on_changed=on_changed)
        self._opened_camera = ft.Text(capture_settings_label(None))
        self._empty = ft.Column(
            controls=[
                ft.Text("No Profile selected."),
                ft.Text(_EMPTY_MESSAGE),
            ],
            spacing=4,
            visible=False,
            key="profile-empty-state",
        )
        self._body = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Column(
                            controls=[self.source.control],
                            expand=True,
                            spacing=8,
                        ),
                        ft.Column(
                            controls=[
                                self.preview.control,
                                self._opened_camera,
                            ],
                            expand=True,
                            spacing=8,
                        ),
                    ],
                    spacing=16,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Divider(),
                self.frame_processing.control,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        self._control = ft.Column(
            controls=[self._empty, self._body],
            spacing=8,
            expand=True,
        )

    @property
    def control(self) -> ft.Control:
        return self._control

    @property
    def opened_camera_label(self) -> ft.Text:
        return self._opened_camera

    def set_profile_present(self, present: bool) -> bool:
        """Show the input controls or the no-Profile empty state."""

        changed = False
        if self._empty.visible == present:
            self._empty.visible = not present
            changed = True
        if self._body.visible != present:
            self._body.visible = present
            changed = True
        return changed

    def apply(self, draft: EditableProfile, permission: EditPermission) -> bool:
        changed = self.set_profile_present(True)
        changed |= self.source.apply(draft, permission)
        changed |= self.frame_processing.apply(draft, permission)
        return changed

    def populate(self, draft: EditableProfile) -> None:
        self.source.populate(draft)

    def set_capture_settings(self, settings: CameraCaptureSettings | None) -> bool:
        label = capture_settings_label(settings)
        if self._opened_camera.value == label:
            return False
        self._opened_camera.value = label
        return True

    def stop_ndi(self) -> None:
        self.source.stop_ndi()
