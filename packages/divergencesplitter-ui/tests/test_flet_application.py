from __future__ import annotations

import asyncio
import json
import tempfile
import threading
from pathlib import Path
from typing import cast

import flet as ft
from divergencesplitter import LiveSplitConnection
from divergencesplitter_runtime.configuration.models import (
    AppSettings,
    InstanceConfiguration,
    Profile,
    Theme,
    VideoSourceConfiguration,
)
from divergencesplitter_runtime.configuration.profile_json import save_profile
from divergencesplitter_ui.configuration.actions import ProfileActions
from divergencesplitter_ui.configuration.profile_header import ProfileHeader
from divergencesplitter_ui.error_dialog import ErrorDialog
from divergencesplitter_ui.flet_application import FletApplication
from divergencesplitter_ui.monitor.coordinator import MonitorUpdateCoordinator
from divergencesplitter_ui.monitor.diagnostics import DiagnosticsPanel
from divergencesplitter_ui.monitor.page import Monitor, MonitorUpdate
from divergencesplitter_ui.navigation import (
    COLLAPSED_NAVIGATION_WIDTH,
    EXPANDED_NAVIGATION_WIDTH,
    AppView,
    Navigation,
)
from divergencesplitter_ui.profile.page import ProfilePage
from divergencesplitter_ui.session import SessionController, SessionState

BASE = Path.cwd()


class FakeController:
    """Duck-typed stand-in recording the lifecycle calls the app makes."""

    def __init__(self) -> None:
        self.state = SessionState.IDLE
        self.diagnostics = None
        self.result = None
        self.started: list[Path] = []
        self.started_settings: list[AppSettings] = []
        self.request_stop_calls = 0
        self.join_calls: list[int] = []

    def start(self, profile: Path, *, app_settings: AppSettings) -> None:
        self.started.append(Path(profile))
        self.started_settings.append(app_settings)

    def request_stop(self) -> None:
        self.request_stop_calls += 1

    def join(self, timeout: float | None = None) -> bool:
        self.join_calls.append(threading.get_ident())
        return True


def make_application(
    *,
    profile: Path | None = None,
    settings_path: Path | None = None,
) -> tuple[FletApplication, FakeController]:
    fake = FakeController()
    application = FletApplication(
        cast(SessionController, fake),
        initial_profile=profile,
        settings_path=settings_path or Path(tempfile.mkdtemp()) / "settings.json",
    )
    return application, fake


def sample_profile() -> Profile:
    return Profile(
        version=1,
        source=VideoSourceConfiguration(str(BASE / "run.mp4")),
        instances=(
            InstanceConfiguration(
                LiveSplitConnection("rpc", "event"),
                str(BASE / "scenario.py"),
            ),
        ),
    )


def write_profile(path: Path) -> Profile:
    profile = sample_profile()
    save_profile(path, profile)
    return profile


def write_settings(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


class TestStartupProfileSelection:
    def test_explicit_profile_starts_and_becomes_last_profile(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "smw.json"
        write_profile(path)
        settings_path = tmp_path / "settings.json"
        application, fake = make_application(profile=path, settings_path=settings_path)

        assert application.start_session() is True

        assert fake.started == [path.resolve()]
        stored = json.loads(settings_path.read_text(encoding="utf-8"))
        assert stored["last_profile"] == str(path.resolve())

    def test_no_profile_leaves_the_session_idle(self, tmp_path: Path) -> None:
        application, fake = make_application(settings_path=tmp_path / "settings.json")

        assert application.start_session() is False

        assert fake.started == []

    def test_last_profile_is_restored(self, tmp_path: Path) -> None:
        path = tmp_path / "smw.json"
        write_profile(path)
        settings_path = tmp_path / "settings.json"
        write_settings(
            settings_path,
            {
                "version": 1,
                "log_level": "OFF",
                "reaction_time_ms": 0,
                "last_profile": str(path),
            },
        )
        application, fake = make_application(settings_path=settings_path)

        assert application.start_session() is True

        assert fake.started == [path.resolve()]

    def test_missing_last_profile_target_leaves_unselected(
        self, tmp_path: Path
    ) -> None:
        settings_path = tmp_path / "settings.json"
        write_settings(
            settings_path,
            {
                "version": 1,
                "log_level": "OFF",
                "reaction_time_ms": 0,
                "last_profile": str(tmp_path / "missing.json"),
            },
        )
        application, fake = make_application(settings_path=settings_path)

        assert application.start_session() is False

        assert fake.started == []

    def test_invalid_last_profile_target_leaves_unselected(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "broken.json"
        path.write_text("{ not valid", encoding="utf-8")
        settings_path = tmp_path / "settings.json"
        write_settings(
            settings_path,
            {
                "version": 1,
                "log_level": "OFF",
                "reaction_time_ms": 0,
                "last_profile": str(path),
            },
        )
        application, fake = make_application(settings_path=settings_path)

        assert application.start_session() is False

        assert fake.started == []

    def test_invalid_app_settings_discards_last_profile(self, tmp_path: Path) -> None:
        valid = tmp_path / "smw.json"
        write_profile(valid)
        settings_path = tmp_path / "settings.json"
        write_settings(
            settings_path,
            {
                "version": 1,
                "log_level": "DEBUG",
                "reaction_time_ms": "broken",
                "last_profile": str(valid),
            },
        )
        application, fake = make_application(settings_path=settings_path)

        assert application.start_session() is False

        assert fake.started == []
        assert application._model.app_settings_document().last_profile is None

    def test_invalid_app_settings_is_not_overwritten_on_startup(
        self, tmp_path: Path
    ) -> None:
        settings_path = tmp_path / "settings.json"
        original = json.dumps(
            {
                "version": 1,
                "log_level": "DEBUG",
                "reaction_time_ms": "broken",
                "last_profile": None,
            }
        )
        settings_path.write_text(original, encoding="utf-8")
        application, fake = make_application(settings_path=settings_path)

        application.start_session()

        assert settings_path.read_text(encoding="utf-8") == original
        assert fake.started == []

    def test_explicit_profile_wins_over_last_profile(self, tmp_path: Path) -> None:
        explicit = tmp_path / "explicit.json"
        write_profile(explicit)
        last = tmp_path / "last.json"
        write_profile(last)
        settings_path = tmp_path / "settings.json"
        write_settings(
            settings_path,
            {
                "version": 1,
                "log_level": "OFF",
                "reaction_time_ms": 0,
                "last_profile": str(last),
            },
        )
        application, fake = make_application(
            profile=explicit, settings_path=settings_path
        )

        assert application.start_session() is True

        assert fake.started == [explicit.resolve()]

    def test_loaded_app_settings_reach_the_runtime(self, tmp_path: Path) -> None:
        path = tmp_path / "smw.json"
        write_profile(path)
        settings_path = tmp_path / "settings.json"
        write_settings(
            settings_path,
            {
                "version": 1,
                "log_level": "DEBUG",
                "reaction_time_ms": 30,
                "last_profile": str(path),
            },
        )
        application, fake = make_application(settings_path=settings_path)

        application.start_session()

        assert fake.started_settings[0].log_level == "DEBUG"
        assert fake.started_settings[0].reaction_time_ms == 30
        assert fake.started_settings[0].last_profile is None


class TestShutdown:
    def test_requests_stop_and_joins_off_the_event_loop(self) -> None:
        application, fake = make_application()

        async def scenario() -> int:
            await application.shutdown()
            return threading.get_ident()

        event_loop_thread = asyncio.run(scenario())

        assert fake.request_stop_calls == 1
        assert len(fake.join_calls) == 1
        assert fake.join_calls[0] != event_loop_thread

    def test_repeated_shutdown_is_ignored(self) -> None:
        application, fake = make_application()

        async def scenario() -> None:
            await application.shutdown()
            await application.shutdown()

        asyncio.run(scenario())

        assert fake.request_stop_calls == 1
        assert len(fake.join_calls) == 1


class _RecordingPage:
    def __init__(self) -> None:
        self.updates: list[tuple] = []

    def update(self, *controls) -> None:
        self.updates.append(controls)


def _views() -> dict[AppView, ft.Container]:
    return {view: ft.Container(visible=view is AppView.MONITOR) for view in AppView}


def _item_icon(navigation: Navigation, view: AppView) -> ft.Icon:
    row = cast(ft.Row, navigation.items[view].content)
    return cast(ft.Icon, row.controls[0])


def _item_label(navigation: Navigation, view: AppView) -> ft.Text:
    row = cast(ft.Row, navigation.items[view].content)
    return cast(ft.Text, row.controls[1])


def _toggle_icon(navigation: Navigation) -> ft.Icon:
    return cast(ft.Icon, navigation.toggle.content)


class TestNavigation:
    def test_view_order_starts_with_monitor(self) -> None:
        assert [view.value for view in AppView] == [
            "monitor",
            "diagnostics",
            "profile",
            "settings",
            "about",
        ]

    def test_settings_and_about_sit_below_the_spacer(self) -> None:
        navigation = Navigation(on_select=lambda view: None)

        column = cast(ft.Column, navigation.control.content)
        controls = column.controls

        spacer_index = controls.index(navigation.spacer)
        assert controls.index(navigation.items[AppView.PROFILE]) < spacer_index
        assert controls.index(navigation.items[AppView.SETTINGS]) > spacer_index
        assert controls.index(navigation.items[AppView.ABOUT]) > spacer_index

    def test_selecting_profile_does_not_stop_runtime(self) -> None:
        application, fake = make_application()
        application._views = _views()
        application._page = cast(ft.Page, _RecordingPage())

        application._select_view(AppView.PROFILE)

        assert fake.request_stop_calls == 0
        assert application.active_view is AppView.PROFILE
        assert application._views[AppView.PROFILE].visible is True
        assert application._views[AppView.MONITOR].visible is False

    def test_selecting_settings_does_not_stop_runtime(self) -> None:
        application, fake = make_application()
        application._views = _views()
        application._page = cast(ft.Page, _RecordingPage())

        application._select_view(AppView.SETTINGS)

        assert fake.request_stop_calls == 0
        assert application.active_view is AppView.SETTINGS
        assert application._views[AppView.SETTINGS].visible is True
        assert application._views[AppView.PROFILE].visible is False

    def test_selecting_about_does_not_stop_runtime(self) -> None:
        application, fake = make_application()
        application._views = _views()
        application._page = cast(ft.Page, _RecordingPage())

        application._select_view(AppView.ABOUT)

        assert fake.request_stop_calls == 0
        assert application.active_view is AppView.ABOUT
        assert application._views[AppView.ABOUT].visible is True
        assert application._views[AppView.MONITOR].visible is False


class TestNavigationCollapse:
    def test_starts_collapsed_with_icon_only_items(self) -> None:
        navigation = Navigation(on_select=lambda view: None)

        assert navigation.expanded is False
        assert navigation.control.width == COLLAPSED_NAVIGATION_WIDTH
        for view in AppView:
            label = _item_label(navigation, view)
            assert label.visible is False
            assert navigation.items[view].tooltip == label.value

    def test_expand_reveals_labels_and_drops_item_tooltips(self) -> None:
        navigation = Navigation(on_select=lambda view: None)

        navigation.toggle_expanded()

        assert navigation.expanded is True
        assert navigation.control.width == EXPANDED_NAVIGATION_WIDTH
        for view in AppView:
            assert _item_label(navigation, view).visible is True
            assert navigation.items[view].tooltip is None
        assert navigation.toggle.tooltip == "Collapse navigation"

    def test_toggle_icon_follows_the_expand_state(self) -> None:
        navigation = Navigation(on_select=lambda view: None)

        assert _toggle_icon(navigation).icon == ft.Icons.CHEVRON_RIGHT
        assert navigation.toggle.tooltip == "Expand navigation"

        navigation.toggle_expanded()

        assert _toggle_icon(navigation).icon == ft.Icons.CHEVRON_LEFT

    def test_collapse_restores_the_starting_layout(self) -> None:
        navigation = Navigation(on_select=lambda view: None)

        navigation.toggle_expanded()
        navigation.toggle_expanded()

        assert navigation.expanded is False
        assert navigation.control.width == COLLAPSED_NAVIGATION_WIDTH
        for view in AppView:
            label = _item_label(navigation, view)
            assert label.visible is False
            assert navigation.items[view].tooltip == label.value
        assert navigation.toggle.tooltip == "Expand navigation"
        assert _toggle_icon(navigation).icon == ft.Icons.CHEVRON_RIGHT

    def test_toggling_reuses_the_same_item_controls(self) -> None:
        navigation = Navigation(on_select=lambda view: None)
        before = dict(navigation.items)
        labels_before = {view: _item_label(navigation, view) for view in AppView}

        navigation.toggle_expanded()
        navigation.toggle_expanded()

        assert navigation.items == before
        for view in AppView:
            assert _item_label(navigation, view) is labels_before[view]

    def test_toggling_does_not_change_the_selected_view(self) -> None:
        navigation = Navigation(on_select=lambda view: None, selected=AppView.MONITOR)

        navigation.toggle_expanded()
        navigation.toggle_expanded()

        assert navigation.selected is AppView.MONITOR

    def test_selected_view_stays_highlighted_in_both_states(self) -> None:
        navigation = Navigation(on_select=lambda view: None, selected=AppView.PROFILE)
        highlight = ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY)

        assert navigation.items[AppView.PROFILE].bgcolor == highlight
        assert _item_icon(navigation, AppView.PROFILE).color == ft.Colors.PRIMARY
        assert _item_label(navigation, AppView.PROFILE).color == ft.Colors.PRIMARY

        navigation.toggle_expanded()

        assert navigation.items[AppView.PROFILE].bgcolor == highlight
        assert _item_icon(navigation, AppView.PROFILE).color == ft.Colors.PRIMARY
        assert _item_label(navigation, AppView.PROFILE).color == ft.Colors.PRIMARY
        assert navigation.selected is AppView.PROFILE

    def test_toggle_and_item_order_are_preserved_across_states(self) -> None:
        navigation = Navigation(on_select=lambda view: None)
        column = cast(ft.Column, navigation.control.content)
        controls = column.controls
        spacer_index = controls.index(navigation.spacer)

        assert controls.index(navigation.toggle) < spacer_index
        for view in (AppView.MONITOR, AppView.DIAGNOSTICS, AppView.PROFILE):
            assert controls.index(navigation.items[view]) < spacer_index
        for view in (AppView.SETTINGS, AppView.ABOUT):
            assert controls.index(navigation.items[view]) > spacer_index

        navigation.toggle_expanded()

        for view in (AppView.MONITOR, AppView.DIAGNOSTICS, AppView.PROFILE):
            assert controls.index(navigation.items[view]) < spacer_index
        for view in (AppView.SETTINGS, AppView.ABOUT):
            assert controls.index(navigation.items[view]) > spacer_index


class _FakeSnapshot:
    def __init__(self) -> None:
        self.tree = None
        self.observations: tuple = ()
        self.run_infos: tuple = ()
        self.instance_statuses: tuple = ()


class _FakeCoordinator:
    def snapshot(self):
        return _FakeSnapshot()


class _FakeMonitor:
    def __init__(
        self, update: MonitorUpdate | None = None, controls: tuple = ()
    ) -> None:
        self._update = update if update is not None else MonitorUpdate()
        self._controls = controls
        self.apply_calls = 0

    def apply(self, snapshot) -> MonitorUpdate:
        self.apply_calls += 1
        return self._update

    def controls_for_update(self, update: MonitorUpdate) -> tuple:
        return self._controls


class _StubProfilePage:
    def __init__(
        self,
        *,
        changed: bool = False,
        preview_changed: bool = False,
        preview_targets: tuple = (),
    ) -> None:
        self._changed = changed
        self._preview_changed = preview_changed
        self._preview_targets = preview_targets
        self.control = ft.Text("profile")
        self.populate_calls = 0
        self.ticks: list[bool] = []

    def tick(self, state, *, visible: bool) -> bool:
        self.ticks.append(visible)
        return self._changed if visible else False

    def populate(self) -> None:
        self.populate_calls += 1

    async def pump_preview(self) -> bool:
        return self._preview_changed

    def preview_update_targets(self) -> tuple:
        return self._preview_targets


class _StubHeader:
    def __init__(self, *, changed: bool = False) -> None:
        self._changed = changed
        self.control = ft.Text("header")
        self.calls = 0
        self.last: dict = {}

    def sync(self, **kwargs) -> bool:
        self.calls += 1
        self.last = kwargs
        return self._changed

    def set_theme(self, theme: Theme) -> None:
        self.themes = getattr(self, "themes", [])
        self.themes.append(theme)


class _StubActions:
    def __init__(self) -> None:
        self.status = ""
        self.calls: list[tuple] = []

    def set_status(self, message: str) -> None:
        self.status = message

    def advance(self, state) -> bool:
        self.calls.append(("advance", state))
        return False


class _StubDialog:
    def __init__(self, shown: bool = False) -> None:
        self._shown = shown
        self.tick_calls = 0

    def tick(self, result) -> bool:
        self.tick_calls += 1
        return self._shown


class _StubDiagnostics:
    def __init__(self, *, changed: bool = False) -> None:
        self._changed = changed
        self.control = ft.Text("diagnostics")
        self.calls: list[bool] = []

    def apply(self, tree, observations, run_infos, statuses, *, visible: bool) -> bool:
        self.calls.append(visible)
        return self._changed if visible else False

    def set_theme(self, theme: Theme) -> None:
        self.themes = getattr(self, "themes", [])
        self.themes.append(theme)


def _application_with(
    page: _RecordingPage,
    monitor: _FakeMonitor,
    *,
    diagnostics: _StubDiagnostics | None = None,
    profile: _StubProfilePage | None = None,
    header: _StubHeader | None = None,
    actions: _StubActions | None = None,
    dialog: _StubDialog | None = None,
) -> FletApplication:
    application, _ = make_application()
    application._page = cast(ft.Page, page)
    application._monitor = cast(Monitor, monitor)
    application._coordinator = cast(MonitorUpdateCoordinator, _FakeCoordinator())
    if diagnostics is not None:
        application._diagnostics = cast(DiagnosticsPanel, diagnostics)
    if profile is not None:
        application._profile_page = cast(ProfilePage, profile)
    if header is not None:
        application._header = cast(ProfileHeader, header)
    if actions is not None:
        application._profile_actions = cast(ProfileActions, actions)
    if dialog is not None:
        application._error_dialog = cast(ErrorDialog, dialog)
    return application


class TestTargetedMonitorUpdates:
    def test_patches_only_the_changed_panel_controls(self) -> None:
        page = _RecordingPage()
        first = ft.Text("first")
        second = ft.Text("second")
        monitor = _FakeMonitor(
            MonitorUpdate(global_status=True, scenario_overview=True),
            (first, second),
        )
        application = _application_with(page, monitor)

        asyncio.run(application._apply_monitor())

        assert page.updates == [(first, second)]

    def test_header_change_patches_only_the_header(self) -> None:
        page = _RecordingPage()
        header = _StubHeader(changed=True)
        application = _application_with(page, _FakeMonitor(), header=header)

        asyncio.run(application._apply_monitor())

        assert header.calls == 1
        assert page.updates == [(header.control,)]

    def test_header_is_synced_on_every_view(self) -> None:
        page = _RecordingPage()
        header = _StubHeader()
        application = _application_with(page, _FakeMonitor(), header=header)
        application._active_view = AppView.SETTINGS

        asyncio.run(application._apply_monitor())

        assert header.calls == 1

    def test_hidden_profile_page_change_is_not_targeted(self) -> None:
        page = _RecordingPage()
        profile = _StubProfilePage(changed=True)
        application = _application_with(page, _FakeMonitor(), profile=profile)

        asyncio.run(application._apply_monitor())

        assert profile.ticks == [False]
        assert page.updates == []

    def test_active_profile_page_change_targets_its_control(self) -> None:
        page = _RecordingPage()
        profile = _StubProfilePage(changed=True)
        application = _application_with(page, _FakeMonitor(), profile=profile)
        application._active_view = AppView.PROFILE

        asyncio.run(application._apply_monitor())

        assert page.updates == [(profile.control,)]

    def test_shown_error_dialog_does_not_force_a_panel_repaint(self) -> None:
        page = _RecordingPage()
        dialog = _StubDialog(shown=True)
        application = _application_with(page, _FakeMonitor(), dialog=dialog)

        asyncio.run(application._apply_monitor())

        assert dialog.tick_calls == 1
        assert page.updates == []


class TestProfileHeaderState:
    def test_dirty_marker_is_synced_while_monitor_is_showing(self) -> None:
        page = _RecordingPage()
        header = _StubHeader()
        application = _application_with(page, _FakeMonitor(), header=header)
        application._model.create_default_profile(Path("draft.json"))

        asyncio.run(application._apply_monitor())

        assert header.last["path_text"].endswith(" *")
        assert header.last["save_enabled"] is True

    def test_advance_runs_on_every_view(self) -> None:
        page = _RecordingPage()
        actions = _StubActions()
        application = _application_with(page, _FakeMonitor(), actions=actions)
        application._active_view = AppView.ABOUT

        asyncio.run(application._apply_monitor())

        assert actions.calls == [("advance", SessionState.IDLE)]


class TestProfileActionsOutsideProfileView:
    def test_run_profile_action_works_from_monitor(self) -> None:
        page = _RecordingPage()
        profile = _StubProfilePage()
        header = _StubHeader(changed=True)
        actions = _StubActions()
        application = _application_with(
            page, _FakeMonitor(), profile=profile, header=header, actions=actions
        )
        called: list[SessionState] = []

        async def action(state):
            called.append(state)
            return True

        application._active_view = AppView.MONITOR
        asyncio.run(application._run_profile_action(action))

        assert called == [SessionState.IDLE]
        assert profile.populate_calls == 1
        assert header.calls == 1
        # The hidden Profile page is not repainted; only the always-visible
        # header is targeted while the Monitor is showing.
        assert page.updates == [(header.control,)]


class _ThemePage:
    def __init__(self) -> None:
        self.theme = "unset"
        self.dark_theme = "unset"
        self.theme_mode = None
        self.update_calls = 0

    def update(self, *controls) -> None:
        self.update_calls += 1


class _ThemePanel:
    def __init__(self) -> None:
        self.themes: list[Theme] = []

    def set_theme(self, theme: Theme) -> None:
        self.themes.append(theme)


class TestThemeApplication:
    def test_apply_theme_sets_the_page_header_and_panels(self) -> None:
        application, _ = make_application()
        page = _ThemePage()
        application._page = cast(ft.Page, page)
        monitor = _ThemePanel()
        diagnostics = _ThemePanel()
        header = _ThemePanel()
        application._monitor = cast(Monitor, monitor)
        application._diagnostics = cast(DiagnosticsPanel, diagnostics)
        application._header = cast(ProfileHeader, header)

        application._apply_theme(Theme.DARK)

        assert page.theme_mode is ft.ThemeMode.DARK
        assert page.theme is None
        assert isinstance(page.dark_theme, ft.Theme)
        assert monitor.themes == [Theme.DARK]
        assert diagnostics.themes == [Theme.DARK]
        assert header.themes == [Theme.DARK]
        assert page.update_calls == 1


class TestProfilePreviewTargets:
    def test_preview_change_patches_only_preview_targets(self) -> None:
        page = _RecordingPage()
        preview_control = ft.Text("preview")
        profile = _StubProfilePage(
            preview_changed=True, preview_targets=(preview_control,)
        )
        application = _application_with(page, _FakeMonitor(), profile=profile)
        application._active_view = AppView.PROFILE

        asyncio.run(application._apply_profile_preview())

        assert page.updates == [(preview_control,)]

    def test_preview_skipped_when_profile_hidden(self) -> None:
        page = _RecordingPage()
        profile = _StubProfilePage(
            preview_changed=True, preview_targets=(ft.Text("preview"),)
        )
        application = _application_with(page, _FakeMonitor(), profile=profile)

        asyncio.run(application._apply_profile_preview())

        assert page.updates == []
