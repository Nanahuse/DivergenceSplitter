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
from divergencesplitter_ui.configuration.page import ConfigurationPage
from divergencesplitter_ui.error_dialog import ErrorDialog
from divergencesplitter_ui.flet_application import AppView, FletApplication
from divergencesplitter_ui.monitor.coordinator import MonitorUpdateCoordinator
from divergencesplitter_ui.monitor.diagnostics import DiagnosticsPanel
from divergencesplitter_ui.monitor.page import Monitor, MonitorUpdate
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


class TestNavigation:
    def test_view_order_includes_diagnostics_after_monitor(self) -> None:
        assert [view.value for view in AppView] == [
            "monitor",
            "diagnostics",
            "configuration",
            "about",
        ]

    def test_switching_to_diagnostics_does_not_stop_runtime(self) -> None:
        application, fake = make_application()
        application._monitor_view = ft.Container()
        application._diagnostics_view = ft.Container(visible=False)
        application._configuration_view = ft.Container(visible=False)
        rail = ft.NavigationRail(selected_index=1)

        application._on_navigate(ft.Event("change", rail))

        assert fake.request_stop_calls == 0
        assert application.active_view == "diagnostics"
        assert application._diagnostics_view.visible is True
        assert application._monitor_view.visible is False
        assert application._configuration_view.visible is False

    def test_switching_to_configuration_does_not_stop_runtime(self) -> None:
        application, fake = make_application()
        application._monitor_view = ft.Container()
        application._diagnostics_view = ft.Container(visible=False)
        application._configuration_view = ft.Container(visible=False)
        rail = ft.NavigationRail(selected_index=2)

        application._on_navigate(ft.Event("change", rail))

        assert fake.request_stop_calls == 0
        assert application.active_view == "configuration"
        assert application._configuration_view.visible is True
        assert application._monitor_view.visible is False
        assert application._diagnostics_view.visible is False

    def test_switching_to_about_does_not_stop_runtime(self) -> None:
        application, fake = make_application()
        application._monitor_view = ft.Container()
        application._diagnostics_view = ft.Container(visible=False)
        application._configuration_view = ft.Container(visible=False)
        application._about_view = ft.Container(visible=False)
        rail = ft.NavigationRail(selected_index=3)

        application._on_navigate(ft.Event("change", rail))

        assert fake.request_stop_calls == 0
        assert application.active_view == "about"
        assert application._about_view.visible is True
        assert application._monitor_view.visible is False
        assert application._configuration_view.visible is False
        assert application._diagnostics_view.visible is False

    def test_switching_back_to_monitor_restores_visibility(self) -> None:
        application, _ = make_application()
        application._monitor_view = ft.Container(visible=False)
        application._diagnostics_view = ft.Container(visible=False)
        application._configuration_view = ft.Container()
        rail = ft.NavigationRail(selected_index=0)

        application._on_navigate(ft.Event("change", rail))

        assert application.active_view == "monitor"
        assert application._monitor_view.visible is True
        assert application._configuration_view.visible is False
        assert application._diagnostics_view.visible is False


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


class _RecordingPage:
    def __init__(self) -> None:
        self.updates: list[tuple] = []

    def update(self, *controls) -> None:
        self.updates.append(controls)


class _StubConfiguration:
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
        self.control = ft.Text("configuration")

    def tick(self, state, *, visible: bool) -> bool:
        return self._changed

    async def pump_preview(self) -> bool:
        return self._preview_changed

    def preview_update_targets(self) -> tuple:
        return self._preview_targets


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


def _application_with(
    page: _RecordingPage,
    monitor: _FakeMonitor,
    *,
    configuration: _StubConfiguration | None = None,
    dialog: _StubDialog | None = None,
    diagnostics: _StubDiagnostics | None = None,
) -> FletApplication:
    application, _ = make_application()
    application._page = cast(ft.Page, page)
    application._monitor = cast(Monitor, monitor)
    application._coordinator = cast(MonitorUpdateCoordinator, _FakeCoordinator())
    if configuration is not None:
        application._configuration = cast(ConfigurationPage, configuration)
    if dialog is not None:
        application._error_dialog = cast(ErrorDialog, dialog)
    if diagnostics is not None:
        application._diagnostics = cast(DiagnosticsPanel, diagnostics)
    return application


class TestErrorWiring:
    def test_result_is_polled_into_the_error_dialog(self) -> None:
        application, fake = make_application()
        fake.result = "terminal-result"
        recorded: list[object] = []

        class RecordingDialog:
            def tick(self, result) -> bool:
                recorded.append(result)
                return False

        application._monitor = cast(Monitor, _FakeMonitor())
        application._coordinator = cast(MonitorUpdateCoordinator, _FakeCoordinator())
        application._error_dialog = cast(ErrorDialog, RecordingDialog())

        asyncio.run(application._apply_monitor())

        assert recorded == ["terminal-result"]


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

    def test_no_patch_when_nothing_changed(self) -> None:
        page = _RecordingPage()
        application = _application_with(
            page, _FakeMonitor(), configuration=_StubConfiguration()
        )

        asyncio.run(application._apply_monitor())

        assert page.updates == []

    def test_shown_error_dialog_does_not_force_a_panel_repaint(self) -> None:
        page = _RecordingPage()
        dialog = _StubDialog(shown=True)
        application = _application_with(page, _FakeMonitor(), dialog=dialog)

        asyncio.run(application._apply_monitor())

        assert dialog.tick_calls == 1
        assert page.updates == []

    def test_hidden_configuration_change_is_not_targeted(self) -> None:
        page = _RecordingPage()
        configuration = _StubConfiguration(changed=True)
        application = _application_with(
            page, _FakeMonitor(), configuration=configuration
        )

        asyncio.run(application._apply_monitor())

        assert page.updates == []

    def test_active_configuration_change_targets_its_control(self) -> None:
        page = _RecordingPage()
        configuration = _StubConfiguration(changed=True)
        application = _application_with(
            page, _FakeMonitor(), configuration=configuration
        )
        application._active_view = AppView.CONFIGURATION

        asyncio.run(application._apply_monitor())

        assert page.updates == [(configuration.control,)]


class TestDiagnosticsUpdates:
    def test_hidden_diagnostics_is_applied_as_hidden(self) -> None:
        page = _RecordingPage()
        diagnostics = _StubDiagnostics(changed=True)
        application = _application_with(page, _FakeMonitor(), diagnostics=diagnostics)

        asyncio.run(application._apply_monitor())

        assert diagnostics.calls == [False]
        assert page.updates == []

    def test_active_diagnostics_change_targets_its_control(self) -> None:
        page = _RecordingPage()
        diagnostics = _StubDiagnostics(changed=True)
        application = _application_with(page, _FakeMonitor(), diagnostics=diagnostics)
        application._active_view = AppView.DIAGNOSTICS

        asyncio.run(application._apply_monitor())

        assert diagnostics.calls == [True]
        assert page.updates == [(diagnostics.control,)]

    def test_active_diagnostics_without_change_does_not_patch(self) -> None:
        page = _RecordingPage()
        diagnostics = _StubDiagnostics(changed=False)
        application = _application_with(page, _FakeMonitor(), diagnostics=diagnostics)
        application._active_view = AppView.DIAGNOSTICS

        asyncio.run(application._apply_monitor())

        assert diagnostics.calls == [True]
        assert page.updates == []


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
    def test_apply_theme_sets_the_page_and_panels(self) -> None:
        application, _ = make_application()
        page = _ThemePage()
        application._page = cast(ft.Page, page)
        monitor = _ThemePanel()
        diagnostics = _ThemePanel()
        configuration = _ThemePanel()
        application._monitor = cast(Monitor, monitor)
        application._diagnostics = cast(DiagnosticsPanel, diagnostics)
        application._configuration = cast(ConfigurationPage, configuration)

        application._apply_theme(Theme.DARK)

        assert page.theme_mode is ft.ThemeMode.DARK
        assert page.theme is None
        assert isinstance(page.dark_theme, ft.Theme)
        assert monitor.themes == [Theme.DARK]
        assert diagnostics.themes == [Theme.DARK]
        assert configuration.themes == [Theme.DARK]
        assert page.update_calls == 1

    def test_apply_light_theme_keeps_standard_light(self) -> None:
        application, _ = make_application()
        page = _ThemePage()
        application._page = cast(ft.Page, page)

        application._apply_theme(Theme.LIGHT)

        assert page.theme_mode is ft.ThemeMode.LIGHT
        assert page.theme is None


class TestConfigurationPreviewTargets:
    def test_preview_change_patches_only_preview_targets(self) -> None:
        page = _RecordingPage()
        preview_control = ft.Text("preview")
        configuration = _StubConfiguration(
            preview_changed=True, preview_targets=(preview_control,)
        )
        application = _application_with(
            page, _FakeMonitor(), configuration=configuration
        )
        application._active_view = AppView.CONFIGURATION

        asyncio.run(application._apply_configuration_preview())

        assert page.updates == [(preview_control,)]

    def test_preview_without_change_does_not_patch(self) -> None:
        page = _RecordingPage()
        configuration = _StubConfiguration(preview_changed=False)
        application = _application_with(
            page, _FakeMonitor(), configuration=configuration
        )
        application._active_view = AppView.CONFIGURATION

        asyncio.run(application._apply_configuration_preview())

        assert page.updates == []

    def test_preview_skipped_when_configuration_hidden(self) -> None:
        page = _RecordingPage()
        configuration = _StubConfiguration(
            preview_changed=True, preview_targets=(ft.Text("preview"),)
        )
        application = _application_with(
            page, _FakeMonitor(), configuration=configuration
        )

        asyncio.run(application._apply_configuration_preview())

        assert page.updates == []
