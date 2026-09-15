from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import cast

from divergencesplitter_ui.flet_application import FletApplication
from divergencesplitter_ui.session import SessionController, SessionState


class FakeController:
    """Duck-typed stand-in recording the lifecycle calls the app makes."""

    def __init__(self) -> None:
        self.state = SessionState.IDLE
        self.diagnostics = None
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
