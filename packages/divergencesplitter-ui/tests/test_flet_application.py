from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import cast

import flet as ft
from divergencesplitter_ui.error_dialog import ErrorDialog
from divergencesplitter_ui.flet_application import FletApplication
from divergencesplitter_ui.monitor.coordinator import MonitorUpdateCoordinator
from divergencesplitter_ui.monitor.page import Monitor
from divergencesplitter_ui.session import SessionController, SessionState


class FakeController:
    """Duck-typed stand-in recording the lifecycle calls the app makes."""

    def __init__(self) -> None:
        self.state = SessionState.IDLE
        self.diagnostics = None
        self.result = None
        self.started: list[Path] = []
        self.request_stop_calls = 0
        self.join_calls: list[int] = []

    def start(self, configuration: Path) -> None:
        self.started.append(Path(configuration))

    def request_stop(self) -> None:
        self.request_stop_calls += 1

    def join(self, timeout: float | None = None) -> bool:
        self.join_calls.append(threading.get_ident())
        return True


def make_application(
    *,
    configuration: Path | None = None,
) -> tuple[FletApplication, FakeController]:
    fake = FakeController()
    application = FletApplication(
        cast(SessionController, fake),
        initial_configuration=configuration,
    )
    return application, fake


class TestStartSession:
    def test_starts_the_existing_controller_with_the_initial_configuration(
        self,
    ) -> None:
        application, fake = make_application(configuration=Path("config.json"))

        application.start_session()

        assert fake.started == [Path("config.json")]

    def test_no_configuration_leaves_the_session_idle(self) -> None:
        application, fake = make_application()

        application.start_session()

        assert fake.started == []


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
    def test_switching_to_configuration_does_not_stop_runtime(self) -> None:
        application, fake = make_application()
        application._monitor_view = ft.Container()
        application._configuration_view = ft.Container(visible=False)
        rail = ft.NavigationRail(selected_index=1)

        application._on_navigate(ft.Event("change", rail))

        assert fake.request_stop_calls == 0
        assert application.active_view == "configuration"
        assert application._configuration_view.visible is True
        assert application._monitor_view.visible is False

    def test_switching_to_about_does_not_stop_runtime(self) -> None:
        application, fake = make_application()
        application._monitor_view = ft.Container()
        application._configuration_view = ft.Container(visible=False)
        application._about_view = ft.Container(visible=False)
        rail = ft.NavigationRail(selected_index=2)

        application._on_navigate(ft.Event("change", rail))

        assert fake.request_stop_calls == 0
        assert application.active_view == "about"
        assert application._about_view.visible is True
        assert application._monitor_view.visible is False
        assert application._configuration_view.visible is False

    def test_switching_back_to_monitor_restores_visibility(self) -> None:
        application, _ = make_application()
        application._monitor_view = ft.Container(visible=False)
        application._configuration_view = ft.Container()
        rail = ft.NavigationRail(selected_index=0)

        application._on_navigate(ft.Event("change", rail))

        assert application.active_view == "monitor"
        assert application._monitor_view.visible is True
        assert application._configuration_view.visible is False


class _FakeSnapshot:
    pass


class _FakeCoordinator:
    def snapshot(self):
        return _FakeSnapshot()


class _FakeMonitor:
    def apply(self, snapshot) -> bool:
        return False


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
