from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import cast

from divergencesplitter import LiveSplitConnection
from divergencesplitter_runtime.configuration.models import (
    AppSettings,
    InstanceConfiguration,
    Profile,
    VideoSourceConfiguration,
)
from divergencesplitter_runtime.configuration.profile_json import save_profile
from divergencesplitter_ui.flet_application import FletApplication
from divergencesplitter_ui.session import SessionController, SessionState


class FakeController:
    def __init__(self) -> None:
        self.state = SessionState.IDLE
        self.diagnostics = None
        self.result = None
        self.started: list[Path] = []
        self.started_settings: list[AppSettings] = []
        self.request_stop_calls = 0
        self.request_reset_all_calls = 0
        self.join_calls: list[int] = []

    def start(self, profile: Path, *, app_settings: AppSettings) -> None:
        self.started.append(profile)
        self.started_settings.append(app_settings)

    def request_stop(self) -> None:
        self.request_stop_calls += 1

    def request_reset_all(self) -> None:
        self.request_reset_all_calls += 1

    def join(self, timeout: float | None = None) -> bool:
        self.join_calls.append(threading.get_ident())
        return True


def write_profile(path: Path) -> None:
    save_profile(
        path,
        Profile(
            version=1,
            source=VideoSourceConfiguration(str(path.with_suffix(".mp4"))),
            instances=(
                InstanceConfiguration(
                    LiveSplitConnection("rpc", "event"), str(path.with_suffix(".py"))
                ),
            ),
        ),
    )


def make_application(
    *, profile: Path | None = None, settings_path: Path
) -> tuple[FletApplication, FakeController]:
    controller = FakeController()
    application = FletApplication(
        cast(SessionController, controller),
        initial_profile=profile,
        settings_path=settings_path,
    )
    return application, controller


def write_settings(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def valid_settings(last_profile: str | None = None) -> dict[str, object]:
    return {
        "version": 1,
        "log_level": "OFF",
        "reaction_time_ms": 0,
        "last_profile": last_profile,
        "ui": {"theme": "light"},
    }


class TestStartupProfileSelection:
    def test_explicit_profile_starts_and_becomes_last_profile(
        self, tmp_path: Path
    ) -> None:
        profile = tmp_path / "profile.json"
        write_profile(profile)
        application, controller = make_application(
            profile=profile, settings_path=tmp_path / "settings.json"
        )
        application.start_session()
        assert controller.started == [profile]

    def test_no_profile_leaves_the_session_idle(self, tmp_path: Path) -> None:
        application, controller = make_application(
            settings_path=tmp_path / "settings.json"
        )
        application.start_session()
        assert controller.started == []

    def test_last_profile_is_restored(self, tmp_path: Path) -> None:
        profile = tmp_path / "profile.json"
        write_profile(profile)
        settings = tmp_path / "settings.json"
        write_settings(settings, valid_settings(str(profile)))
        application, controller = make_application(settings_path=settings)
        application.start_session()
        assert controller.started == [profile]

    def test_missing_last_profile_target_leaves_unselected(
        self, tmp_path: Path
    ) -> None:
        settings = tmp_path / "settings.json"
        write_settings(settings, valid_settings(str(tmp_path / "missing.json")))
        application, controller = make_application(settings_path=settings)
        application.start_session()
        assert controller.started == []

    def test_invalid_last_profile_target_leaves_unselected(
        self, tmp_path: Path
    ) -> None:
        settings = tmp_path / "settings.json"
        write_settings(settings, valid_settings("relative.json"))
        application, controller = make_application(settings_path=settings)
        application.start_session()
        assert controller.started == []

    def test_invalid_app_settings_discards_last_profile(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        write_settings(settings, {"version": 1, "last_profile": "bad"})
        application, controller = make_application(settings_path=settings)
        application.start_session()
        assert controller.started == []

    def test_invalid_app_settings_is_not_overwritten_on_startup(
        self, tmp_path: Path
    ) -> None:
        settings = tmp_path / "settings.json"
        original = '{"version": 1, "last_profile": "bad"}'
        settings.write_text(original, encoding="utf-8")
        application, _ = make_application(settings_path=settings)
        application.start_session()
        assert settings.read_text(encoding="utf-8") == original

    def test_explicit_profile_wins_over_last_profile(self, tmp_path: Path) -> None:
        explicit = tmp_path / "explicit.json"
        last = tmp_path / "last.json"
        write_profile(explicit)
        write_profile(last)
        settings = tmp_path / "settings.json"
        write_settings(settings, valid_settings(str(last)))
        application, controller = make_application(
            profile=explicit, settings_path=settings
        )
        application.start_session()
        assert controller.started == [explicit]

    def test_loaded_app_settings_reach_the_runtime(self, tmp_path: Path) -> None:
        profile = tmp_path / "profile.json"
        write_profile(profile)
        settings = tmp_path / "settings.json"
        value = valid_settings(str(profile))
        value.update({"log_level": "DEBUG", "reaction_time_ms": 30})
        write_settings(settings, value)
        application, controller = make_application(settings_path=settings)
        application.start_session()
        assert controller.started_settings[0].log_level == "DEBUG"
        assert controller.started_settings[0].reaction_time_ms == 30


class TestShutdown:
    def test_requests_stop_and_joins_off_the_event_loop(self, tmp_path: Path) -> None:
        application, controller = make_application(
            settings_path=tmp_path / "settings.json"
        )

        async def scenario() -> int:
            await application.shutdown()
            return threading.get_ident()

        event_loop_thread = asyncio.run(scenario())
        assert controller.request_stop_calls == 1
        assert controller.join_calls[0] != event_loop_thread

    def test_repeated_shutdown_is_ignored(self, tmp_path: Path) -> None:
        application, controller = make_application(
            settings_path=tmp_path / "settings.json"
        )

        async def scenario() -> None:
            await application.shutdown()
            await application.shutdown()

        asyncio.run(scenario())
        assert controller.request_stop_calls == 1
        assert len(controller.join_calls) == 1


def test_reset_all_callback_forwards_to_the_controller(tmp_path: Path) -> None:
    application, controller = make_application(settings_path=tmp_path / "settings.json")
    application._request_reset_all()
    assert controller.request_reset_all_calls == 1
