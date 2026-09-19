"""Flet Configuration page composing the Profile header and three tabs.

The page uses the single shared ``SettingsModel`` and never keeps a second
settings state. The always-visible Profile header owns the Profile path, dirty
marker, New/Open/Save/Save As, and the global status; New/Open/Save/Save As are
delegated to ``ProfileActions``. The three tabs split the body by
responsibility: Input (``Profile.source``), Scenarios & Connections
(``Profile.instances``), and System (App Settings). The Configuration preview
runs only while the Input tab is active. Runtime restart happens only through
``SessionController`` after a successful save.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum
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
from divergencesplitter_ui.configuration.input_tab import InputTab
from divergencesplitter_ui.configuration.preview import (
    ConfigurationPreview,
    PreviewController,
)
from divergencesplitter_ui.configuration.profile_header import ProfileHeader
from divergencesplitter_ui.configuration.scenarios_tab import ScenariosTab
from divergencesplitter_ui.configuration.system_tab import SystemTab
from divergencesplitter_ui.ndi_discovery import NdiDiscovery
from divergencesplitter_ui.session import SessionController, SessionState, is_active
from divergencesplitter_ui.settings import (
    EditableProfile,
    SettingsModel,
    SourceType,
    edit_permission,
    source_transform_from_editable,
)


class ConfigurationTab(StrEnum):
    """The body tab the Configuration page is showing."""

    INPUT = "input"
    SCENARIOS = "scenarios"
    SYSTEM = "system"


_TAB_ORDER = (
    ConfigurationTab.INPUT,
    ConfigurationTab.SCENARIOS,
    ConfigurationTab.SYSTEM,
)
_TAB_LABELS = {
    ConfigurationTab.INPUT: "Input",
    ConfigurationTab.SCENARIOS: "Scenarios & Connections",
    ConfigurationTab.SYSTEM: "System",
}


class ConfigurationPage:
    """Own the Configuration page, its tabs, and their preview and actions."""

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
        preview_control = preview if preview is not None else ConfigurationPreview()
        self._preview_controller = (
            preview_controller
            if preview_controller is not None
            else PreviewController(
                runtime_frame_provider=self._take_runtime_frame,
                runtime_active=lambda: is_active(self._controller.state),
            )
        )
        self._header = ProfileHeader(
            on_new=self._on_new,
            on_open=self._on_open,
            on_save=self._on_save,
            on_save_as=self._on_save_as,
        )
        self._input = InputTab(
            model,
            dialogs,
            on_input_changed=self._on_input_changed,
            on_changed=self._sync_preview_now,
            preview=preview_control,
            ndi_discovery=ndi_discovery,
        )
        self._scenarios = ScenariosTab(
            model, dialogs, on_changed=self._sync_preview_now
        )
        self._system = SystemTab(
            on_log_level=self._on_log_level,
            on_reaction_time_committed=self._on_reaction_time_committed,
        )
        # Kept as convenience aliases for the composed sections and controls.
        self._source = self._input.source
        self._frame_processing = self._input.frame_processing
        self._instances = self._scenarios.section
        self._log_level = self._system.log_level
        self._reaction_time = self._system.reaction_time
        self._profile_path = self._header.profile_path
        self._new_button = self._header.new_button
        self._open_button = self._header.open_button
        self._save_button = self._header.save_button
        self._save_as_button = self._header.save_as_button

        self._active_tab = ConfigurationTab.INPUT
        self._tabs = ft.Tabs(
            content=ft.Column(
                controls=[
                    ft.TabBar(
                        tabs=[ft.Tab(label=_TAB_LABELS[tab]) for tab in _TAB_ORDER]
                    ),
                    ft.TabBarView(
                        controls=[
                            self._input.control,
                            self._scenarios.control,
                            self._system.control,
                        ],
                        expand=True,
                    ),
                ],
                expand=True,
            ),
            length=len(_TAB_ORDER),
            selected_index=0,
            on_change=self._on_tab_change,
            expand=True,
        )
        self._control = ft.Column(
            controls=[
                ft.Text("Configuration", size=20),
                self._header.control,
                ft.Divider(),
                self._tabs,
            ],
            spacing=10,
            expand=True,
        )
        self._pending_preview_command = None
        self._started_preview_key: tuple | None = None
        self._preview_was_active = False
        self._populated_draft: EditableProfile | None = None
        self._was_visible = False

    @property
    def control(self) -> ft.Control:
        return self._control

    @property
    def actions(self) -> ProfileActions:
        return self._actions

    @property
    def preview(self) -> ConfigurationPreview:
        return self._input.preview

    @property
    def active_tab(self) -> ConfigurationTab:
        return self._active_tab

    def select_tab(self, tab: ConfigurationTab) -> None:
        """Switch the active tab without touching the Profile or runtime."""

        self._active_tab = tab
        self._tabs.selected_index = _TAB_ORDER.index(tab)
        self.tick(self._controller.state, visible=True)

    def preview_update_targets(self) -> tuple[ft.Control, ...]:
        """The controls one ``pump_preview`` cycle can change.

        The preview frame itself streams over ``RawImage``'s data channel, so
        only the preview status text and the opened-camera label need a regular
        Flet patch; the application never repaints the whole page for them.
        """

        return (self._input.preview.control, self._input.opened_camera_label)

    async def pump_preview(self) -> bool:
        """Run one preview cycle: apply any pending start/stop, render a frame."""

        command = self._pending_preview_command
        if command is not None:
            self._pending_preview_command = None
            try:
                await asyncio.to_thread(command)
            except Exception as error:  # noqa: BLE001 - surfaced as preview status
                self._actions.set_status(f"preview: {error}")
        changed = await self._input.preview.pump(self._preview_controller)
        changed |= self._input.set_capture_settings(
            self._preview_controller.capture_settings
        )
        error = self._preview_controller.error
        if error is not None and self._actions.status != f"preview: {error}":
            self._actions.set_status(f"preview: {error}")
        return changed

    def tick(self, state: SessionState, *, visible: bool) -> bool:
        """Sync the page from the model; return whether anything changed."""

        changed = self._actions.advance(state)
        if not visible:
            self._deactivate_preview()
            self._was_visible = False
            return changed
        self._was_visible = True
        permission = edit_permission(state)
        draft = self._model.draft
        changed |= self._sync_header(draft, permission)
        if self._active_tab is ConfigurationTab.INPUT:
            changed |= self._sync_input(draft, permission)
        else:
            self._deactivate_preview()
            if self._active_tab is ConfigurationTab.SCENARIOS:
                changed |= self._scenarios.set_profile_present(draft is not None)
                if draft is not None:
                    changed |= self._instances.apply(draft, permission)
            else:
                changed |= self._system.sync(self._model.app_settings, permission)
        return changed

    def populate(self) -> None:
        """Resync section state (camera lists, NDI sources) from the draft."""

        draft = self._model.draft
        if draft is None:
            self._input.set_profile_present(False)
            self._scenarios.set_profile_present(False)
            return
        self._input.set_profile_present(True)
        self._scenarios.set_profile_present(True)
        self._populate_input(draft)
        self._instances.apply(draft, edit_permission(self._controller.state))
        if self._active_tab is ConfigurationTab.INPUT:
            self._sync_preview(draft)

    def teardown(self) -> None:
        """Stop the draft preview and the NDI worker before shutdown."""

        self._preview_controller.stop()
        self._input.stop_ndi()

    def _sync_header(self, draft: EditableProfile | None, permission) -> bool:
        if draft is None:
            path_text = "No profile selected"
            save_enabled = False
            save_as_enabled = False
        else:
            path_text = str(draft.profile_path)
            if self._model.is_dirty:
                path_text += " *"
            save_enabled = permission.instances
            save_as_enabled = permission.instances
        return self._header.sync(
            path_text=path_text,
            status=self._actions.status,
            new_enabled=permission.instances,
            open_enabled=permission.instances,
            save_enabled=save_enabled,
            save_as_enabled=save_as_enabled,
        )

    def _sync_input(self, draft: EditableProfile | None, permission) -> bool:
        if draft is None:
            changed = self._input.set_profile_present(False)
        else:
            self._populate_input(draft)
            changed = self._input.apply(draft, permission)
            self._sync_preview(draft)
        self._preview_was_active = True
        return changed

    def _populate_input(self, draft: EditableProfile) -> None:
        if self._populated_draft is draft:
            return
        self._input.populate(draft)
        self._populated_draft = draft

    def _deactivate_preview(self) -> None:
        if not self._preview_was_active:
            return
        self._preview_was_active = False
        self._pending_preview_command = self._preview_controller.stop
        self._started_preview_key = None

    def _sync_preview_now(self) -> None:
        draft = self._model.draft
        if draft is not None and self._active_tab is ConfigurationTab.INPUT:
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

    def _on_tab_change(self, event: ft.Event[ft.Tabs]) -> None:
        index = int(event.control.selected_index or 0)
        if 0 <= index < len(_TAB_ORDER):
            self._active_tab = _TAB_ORDER[index]
        self.tick(self._controller.state, visible=True)
        self._request_update()

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
