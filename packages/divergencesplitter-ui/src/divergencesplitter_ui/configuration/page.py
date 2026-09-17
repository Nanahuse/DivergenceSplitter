"""Flet Configuration page composing file actions, source, and preview.

The page uses the single shared ``SettingsModel`` and never keeps a second
settings state. It renders the draft, delegates New/Open/
Save/Save As to ``ProfileActions``, and drives preview lifecycle through
``PreviewController``. Runtime restart happens only through ``SessionController``
after a successful save.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import flet as ft
from divergencesplitter.frame.models import Frame
from divergencesplitter_runtime.configuration.app_settings_json import (
    default_app_settings_path,
)
from divergencesplitter_runtime.configuration.models import (
    CameraSourceConfiguration,
    NdiSourceConfiguration,
    SourceTransformConfiguration,
)
from divergencesplitter_runtime.configuration.source_builder import (
    SourceConfigurationError,
)

from divergencesplitter_ui.configuration.actions import ProfileActions
from divergencesplitter_ui.configuration.dialogs import FileDialogs
from divergencesplitter_ui.configuration.frame_processing import FrameProcessingSection
from divergencesplitter_ui.configuration.instances import InstancesSection
from divergencesplitter_ui.configuration.preview import (
    ConfigurationPreview,
    PreviewController,
    capture_settings_label,
)
from divergencesplitter_ui.configuration.source import SourceSection
from divergencesplitter_ui.ndi_discovery import NdiDiscovery
from divergencesplitter_ui.session import SessionController, SessionState, is_active
from divergencesplitter_ui.settings import (
    EditableProfile,
    SettingsModel,
    SourceType,
    edit_permission,
    source_transform_from_editable,
)

_LOG_FILE_NOTE = "DEBUG log: see diagnostics.log"


class ConfigurationPage:
    """Own the Configuration page and its preview, actions, and sections."""

    def __init__(
        self,
        controller: SessionController,
        model: SettingsModel,
        dialogs: FileDialogs,
        *,
        ndi_discovery: NdiDiscovery | None = None,
        preview: ConfigurationPreview | None = None,
        preview_controller: PreviewController | None = None,
        settings_path: Path | None = None,
    ) -> None:
        self._controller = controller
        self._model = model
        self._dialogs = dialogs
        self._settings_path = (
            settings_path if settings_path is not None else default_app_settings_path()
        )
        self._actions = ProfileActions(
            controller, model, dialogs, settings_path=self._settings_path
        )
        self._preview = preview if preview is not None else ConfigurationPreview()
        self._preview_controller = (
            preview_controller
            if preview_controller is not None
            else PreviewController(
                runtime_frame_provider=self._take_runtime_frame,
                runtime_active=lambda: is_active(self._controller.state),
            )
        )
        self._source = SourceSection(
            model,
            dialogs,
            on_input_changed=self._on_input_changed,
            ndi_discovery=ndi_discovery,
        )
        self._frame_processing = FrameProcessingSection(
            model, on_changed=self._sync_preview_now
        )
        self._instances = InstancesSection(
            model, dialogs, on_changed=self._sync_preview_now
        )
        self._status = ft.Text("", color=ft.Colors.ORANGE_300)
        self._profile_path = ft.TextField(value="", read_only=True, expand=True)
        self._new_button = ft.OutlinedButton(
            content="New Profile...", on_click=self._on_new
        )
        self._open_button = ft.OutlinedButton(
            content="Open Profile...", on_click=self._on_open
        )
        self._save_button = ft.OutlinedButton(content="Save", on_click=self._on_save)
        self._save_as_button = ft.OutlinedButton(
            content="Save Profile As...", on_click=self._on_save_as
        )
        self._opened_camera = ft.Text(capture_settings_label(None))
        self._log_level = ft.Dropdown(
            label="Logging (OFF / DEBUG: all details)",
            options=[ft.DropdownOption(key="OFF"), ft.DropdownOption(key="DEBUG")],
            value="OFF",
            on_select=self._on_log_level,
        )
        self._reaction_time = ft.TextField(
            label="Reaction time (ms)",
            value="0",
            width=200,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_submit=self._on_reaction_time_committed,
            on_blur=self._on_reaction_time_committed,
        )
        self._control = ft.Column(
            controls=[
                ft.Text("Configuration", size=20),
                ft.Row(
                    controls=[
                        self._profile_path,
                        self._new_button,
                        self._open_button,
                        self._save_button,
                        self._save_as_button,
                    ],
                    spacing=8,
                ),
                ft.Divider(),
                ft.Row(
                    controls=[
                        ft.Column(
                            controls=[self._source.control],
                            expand=True,
                            spacing=8,
                        ),
                        ft.Column(
                            controls=[
                                self._preview.control,
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
                self._frame_processing.control,
                ft.Divider(),
                self._instances.control,
                ft.Divider(),
                self._log_level,
                self._reaction_time,
                ft.Text(_LOG_FILE_NOTE),
                self._status,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        self._pending_preview_command = None
        self._started_preview_key: tuple | None = None
        self._was_visible = False

    @property
    def control(self) -> ft.Control:
        return self._control

    @property
    def actions(self) -> ProfileActions:
        return self._actions

    @property
    def preview(self) -> ConfigurationPreview:
        return self._preview

    def preview_update_targets(self) -> tuple[ft.Control, ...]:
        """The controls one ``pump_preview`` cycle can change.

        The preview frame itself streams over ``RawImage``'s data channel, so
        only the preview status text and the opened-camera label need a regular
        Flet patch; the application never repaints the whole page for them.
        """

        return (self._preview.control, self._opened_camera)

    async def pump_preview(self) -> bool:
        """Run one preview cycle: apply any pending start/stop, render a frame."""

        command = self._pending_preview_command
        if command is not None:
            self._pending_preview_command = None
            try:
                await asyncio.to_thread(command)
            except Exception as error:  # noqa: BLE001 - surfaced as preview status
                self._actions.set_status(f"preview: {error}")
        changed = await self._preview.pump(self._preview_controller)
        settings = self._preview_controller.capture_settings
        label = capture_settings_label(settings)
        if self._opened_camera.value != label:
            self._opened_camera.value = label
            changed = True
        error = self._preview_controller.error
        if error is not None and self._actions.status != f"preview: {error}":
            self._actions.set_status(f"preview: {error}")
        return changed

    def tick(self, state: SessionState, *, visible: bool) -> bool:
        """Sync the page from the model; return whether anything changed."""

        changed = self._actions.advance(state)
        if not visible:
            if self._was_visible:
                self._pending_preview_command = self._preview_controller.stop
                self._started_preview_key = None
            self._was_visible = False
            return changed
        self._was_visible = True
        permission = edit_permission(state)
        draft = self._model.draft
        path_text = ""
        if draft is not None:
            path_text = str(draft.profile_path)
            if self._model.is_dirty:
                path_text += " *"
        if self._profile_path.value != path_text:
            self._profile_path.value = path_text
            changed = True
        if self._status.value != self._actions.status:
            self._status.value = self._actions.status
            changed = True
        changed |= self._set_enabled(self._new_button, permission.instances)
        changed |= self._set_enabled(self._open_button, permission.instances)
        changed |= self._set_enabled(
            self._save_button, draft is not None and permission.instances
        )
        changed |= self._set_enabled(self._save_as_button, permission.instances)
        if draft is not None:
            changed |= self._source.apply(draft, permission)
            changed |= self._frame_processing.apply(draft, permission)
            changed |= self._instances.apply(draft, permission)
            self._sync_preview(draft)
        changed |= self._sync_common_fields(permission)
        return changed

    def populate(self) -> None:
        """Resync section state (camera lists, NDI sources) from the draft."""

        draft = self._model.draft
        if draft is None:
            return
        self._source.populate(draft)
        self._sync_preview(draft)

    def teardown(self) -> None:
        """Stop the draft preview and the NDI worker before shutdown."""

        self._preview_controller.stop()
        self._source.stop_ndi()

    def _sync_common_fields(self, permission) -> bool:
        changed = False
        settings = self._model.app_settings
        if self._log_level.value != settings.log_level:
            self._log_level.value = settings.log_level
            changed = True
        if self._reaction_time.value != str(settings.reaction_time_ms):
            self._reaction_time.value = str(settings.reaction_time_ms)
            changed = True
        changed |= self._set_enabled(self._log_level, permission.log_level)
        changed |= self._set_enabled(self._reaction_time, permission.reaction_time)
        return changed

    def _sync_preview_now(self) -> None:
        draft = self._model.draft
        if draft is not None:
            self._sync_preview(draft)

    def _sync_preview(self, draft: EditableProfile) -> None:
        transform = source_transform_from_editable(draft)
        self._preview_controller.update_transform(transform)
        if is_active(self._controller.state):
            if self._started_preview_key is not None:
                self._pending_preview_command = self._preview_controller.stop
                self._started_preview_key = None
            return
        key = self._preview_key(draft)
        if key == self._started_preview_key:
            return
        self._started_preview_key = key
        if key is None:
            self._pending_preview_command = self._preview_controller.stop
            return
        try:
            configuration = self._preview_configuration(draft, transform)
        except (SourceConfigurationError, ValueError) as error:
            self._actions.set_status(f"preview: {error}")
            return
        self._pending_preview_command = lambda: self._preview_controller.start_draft(
            configuration
        )

    def _preview_key(self, draft: EditableProfile) -> tuple | None:
        source = draft.source
        if source.selected_type is SourceType.CAMERA:
            camera = source.camera
            if camera.device is None or camera.mode is None:
                return None
            return ("camera", camera.device, camera.mode, camera.request_60_fps)
        if source.selected_type is SourceType.NDI:
            name = source.ndi.name
            if not name or not self._model.ndi_available:
                return None
            return ("ndi", name)
        return None

    def _preview_configuration(
        self,
        draft: EditableProfile,
        transform: SourceTransformConfiguration,
    ) -> CameraSourceConfiguration | NdiSourceConfiguration:
        source = draft.source
        if source.selected_type is SourceType.CAMERA:
            camera = source.camera
            assert camera.device is not None and camera.mode is not None
            return CameraSourceConfiguration(
                camera.device, camera.mode, camera.request_60_fps, transform
            )
        assert source.selected_type is SourceType.NDI
        return NdiSourceConfiguration(source.ndi.name, transform)

    def _take_runtime_frame(self) -> Frame | None:
        diagnostics = self._controller.diagnostics
        if diagnostics is None:
            return None
        return diagnostics.take_latest_input_frame()

    def _on_input_changed(self) -> None:
        """Record an unsaved source edit without touching the running runtime.

        Editing the draft only changes the draft and synchronizes the preview;
        it never stops or restarts the session. While a session runs, the
        Configuration preview keeps showing its raw input frame, so the draft
        change is deferred until Save. Only ``ProfileActions`` reloads the
        controlled runtime, and only after a successful save.
        """

        self._sync_preview_now()
        self._actions.set_status("Input changed; save to apply.")

    async def _on_new(self, event: ft.Event[ft.OutlinedButton]) -> None:
        await self._run_action(self._actions.new)

    async def _on_open(self, event: ft.Event[ft.OutlinedButton]) -> None:
        await self._run_action(self._actions.open)

    async def _on_save(self, event: ft.Event[ft.OutlinedButton]) -> None:
        await self._run_action(self._actions.save)

    async def _on_save_as(self, event: ft.Event[ft.OutlinedButton]) -> None:
        await self._run_action(self._actions.save_as)

    async def _run_action(self, action) -> None:
        state = self._controller.state
        try:
            await action(state)
        except Exception as error:  # noqa: BLE001 - surfaced as status, not swallowed
            self._actions.set_status(str(error))
        self.populate()
        self.tick(self._controller.state, visible=True)
        self._request_update()

    def _on_log_level(self, event: ft.Event[ft.Dropdown]) -> None:
        # Log level is App Settings: it is persisted and applied live, and it
        # never marks the Profile dirty or restarts the runtime.
        level = self._log_level.value or "DEBUG"
        self._actions.set_log_level(level)
        self._request_update()

    def _on_reaction_time_committed(self, event: ft.Event[ft.TextField]) -> None:
        # Reaction time is App Settings too. Only a committed value (submit or
        # blur) is applied, so a partial number never restarts the runtime.
        try:
            value = int((self._reaction_time.value or "").strip())
        except ValueError:
            self._actions.set_status("reaction time must be a non-negative integer")
            self._request_update()
            return
        self._actions.commit_reaction_time(value)
        self._request_update()

    def _request_update(self) -> None:
        try:
            self._control.update()
        except RuntimeError:
            pass

    @staticmethod
    def _set_enabled(control, enabled: bool) -> bool:
        if control.disabled == enabled:
            control.disabled = not enabled
            return True
        return False
