"""Flet Profile page composing the Input and Scenarios & Connections tabs.

The page edits only what a Profile file stores: ``Profile.source`` and
``Profile.instances``. Application Settings (theme, log level, reaction time)
live on the separate Settings screen. The always-visible Profile header and the
New/Open/Save/Save As operations are owned by ``FletApplication``, so they stay
available on every Current View and every status message is routed back through
``on_status``. The preview runs only while the Profile view is active. The
runtime restarts only through ``ProfileActions`` after a successful save.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from enum import StrEnum

import flet as ft
from divergencesplitter.frame.models import Frame
from divergencesplitter_runtime.configuration.models import (
    CameraSourceConfiguration,
    NdiSourceConfiguration,
    SourceTransformConfiguration,
)
from divergencesplitter_runtime.configuration.source_builder import (
    SourceConfigurationError,
)

from divergencesplitter_ui.configuration.dialogs import FileDialogs
from divergencesplitter_ui.configuration.input_tab import InputTab
from divergencesplitter_ui.configuration.preview import (
    ConfigurationPreview,
    PreviewController,
)
from divergencesplitter_ui.configuration.scenarios_tab import ScenariosTab
from divergencesplitter_ui.ndi_discovery import NdiDiscovery
from divergencesplitter_ui.session import SessionController, SessionState, is_active
from divergencesplitter_ui.settings import (
    EditableProfile,
    SettingsModel,
    SourceType,
    edit_permission,
    source_transform_from_editable,
)


class ProfileTab(StrEnum):
    """The body tab the Profile page is showing."""

    INPUT = "input"
    SCENARIOS = "scenarios"


_TAB_ORDER = (ProfileTab.INPUT, ProfileTab.SCENARIOS)
_TAB_LABELS = {
    ProfileTab.INPUT: "Input",
    ProfileTab.SCENARIOS: "Scenarios & Connections",
}


class ProfilePage:
    """Own the Profile page, its tabs, and their preview."""

    def __init__(
        self,
        controller: SessionController,
        model: SettingsModel,
        dialogs: FileDialogs,
        *,
        on_status: Callable[[str], None],
        ndi_discovery: NdiDiscovery | None = None,
        preview: ConfigurationPreview | None = None,
        preview_controller: PreviewController | None = None,
    ) -> None:
        self._controller = controller
        self._model = model
        self._on_status = on_status
        preview_control = preview if preview is not None else ConfigurationPreview()
        self._preview_controller = (
            preview_controller
            if preview_controller is not None
            else PreviewController(
                runtime_frame_provider=self._take_runtime_frame,
                runtime_active=lambda: is_active(self._controller.state),
            )
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
        # Kept as convenience aliases for the composed sections and controls.
        self._source = self._input.source
        self._frame_processing = self._input.frame_processing
        self._instances = self._scenarios.section

        self._active_tab = ProfileTab.INPUT
        self._tabs = ft.Tabs(
            content=ft.Column(
                controls=[
                    ft.TabBar(
                        tabs=[ft.Tab(label=_TAB_LABELS[tab]) for tab in _TAB_ORDER]
                    ),
                    ft.TabBarView(
                        controls=[self._input.control, self._scenarios.control],
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
                ft.Text("Profile", size=20),
                ft.Text("Changes are not reflected until you save the Profile."),
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
    def preview(self) -> ConfigurationPreview:
        return self._input.preview

    @property
    def active_tab(self) -> ProfileTab:
        return self._active_tab

    def select_tab(self, tab: ProfileTab) -> None:
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
                self._on_status(f"preview: {error}")
        changed = await self._input.preview.pump(self._preview_controller)
        changed |= self._input.set_capture_settings(
            self._preview_controller.capture_settings
        )
        error = self._preview_controller.error
        if error is not None:
            self._on_status(f"preview: {error}")
        return changed

    def tick(self, state: SessionState, *, visible: bool) -> bool:
        """Sync the page from the model; return whether anything changed."""

        if not visible:
            self._deactivate_preview()
            self._was_visible = False
            return False
        self._was_visible = True
        permission = edit_permission(state)
        draft = self._model.draft
        changed = False
        if self._active_tab is ProfileTab.INPUT:
            changed |= self._sync_input(draft, permission)
        else:
            self._deactivate_preview()
            changed |= self._scenarios.set_profile_present(draft is not None)
            if draft is not None:
                changed |= self._instances.apply(draft, permission)
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
        if self._active_tab is ProfileTab.INPUT:
            self._sync_preview(draft)

    def teardown(self) -> None:
        """Stop the draft preview and the NDI worker before shutdown."""

        self._preview_controller.stop()
        self._input.stop_ndi()

    def _sync_input(self, draft: EditableProfile | None, permission) -> bool:
        if not self._preview_was_active:
            # Probe before NDI can be selected: until discovery finishes its
            # source-type option is disabled. Refresh again when Input reopens.
            self._source.refresh_ndi()
        if draft is None:
            changed = self._input.set_profile_present(False)
        else:
            changed = self._populate_input(draft)
            changed |= self._input.apply(draft, permission)
            self._sync_preview(draft)
        self._preview_was_active = True
        return changed

    def _populate_input(self, draft: EditableProfile) -> bool:
        if self._populated_draft is draft:
            return False
        self._input.populate(draft)
        self._populated_draft = draft
        # populate() mutates values and options before apply() compares them.
        # Preserve that change so the application sends the populated controls.
        return True

    def _deactivate_preview(self) -> None:
        if not self._preview_was_active:
            return
        self._preview_was_active = False
        self._pending_preview_command = self._preview_controller.stop
        self._started_preview_key = None

    def _sync_preview_now(self) -> None:
        draft = self._model.draft
        if draft is not None and self._active_tab is ProfileTab.INPUT:
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
            self._on_status(f"preview: {error}")
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
        Profile preview keeps showing its raw input frame, so the draft change
        is deferred until Save. Only ``ProfileActions`` reloads the controlled
        runtime, and only after a successful save.
        """

        self._sync_preview_now()
        self._on_status("Input changed; save to apply.")

    def _request_update(self) -> None:
        try:
            self._control.update()
        except RuntimeError:
            pass
