from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

from divergencesplitter import LiveSplitConnection
from divergencesplitter_runtime.configuration.app_settings_json import (
    load_app_settings,
)
from divergencesplitter_runtime.configuration.models import (
    AppSettings,
    CameraBackend,
    CameraDeviceConfiguration,
    CameraModeConfiguration,
    CameraSourceConfiguration,
    InstanceConfiguration,
    Profile,
    Theme,
)
from divergencesplitter_ui.session import SessionController, SessionState
from divergencesplitter_ui.settings import CameraDevice, SettingsModel
from divergencesplitter_ui.settings.actions import AppSettingsActions

BASE = Path.cwd()


def p(name: str) -> str:
    return str(BASE / name)


class FakeCameraEnumerator:
    def list_devices(self) -> list[CameraDevice]:
        return cast(
            list[CameraDevice],
            [
                SimpleNamespace(
                    backend=SimpleNamespace(name="DIRECT_SHOW"),
                    name="USB Camera",
                    index=7,
                    modes=[
                        SimpleNamespace(
                            width=1280, height=720, fps=60.0, subtype_guid="X"
                        )
                    ],
                )
            ],
        )


class FakeController:
    def __init__(self) -> None:
        self.state = SessionState.IDLE
        self.diagnostics = None
        self.started: list[Path] = []
        self.started_settings: list[AppSettings] = []
        self.request_stop_calls = 0
        self.join_calls = 0
        self.log_levels: list[str] = []

    def start(self, path, *, app_settings) -> None:
        self.started.append(Path(path))
        self.started_settings.append(app_settings)

    def request_stop(self) -> None:
        self.request_stop_calls += 1

    def join(self, timeout: float | None = None) -> bool:
        self.join_calls += 1
        return True

    def set_log_level(self, level: str) -> None:
        self.log_levels.append(level)


def camera_profile() -> Profile:
    return Profile(
        version=1,
        source=CameraSourceConfiguration(
            CameraDeviceConfiguration(CameraBackend.DIRECT_SHOW, "USB Camera", 2),
            CameraModeConfiguration(1280, 720, 60.0, "MJPG"),
            False,
        ),
        instances=(
            InstanceConfiguration(
                LiveSplitConnection("rpc", "event"), p("scenario.py")
            ),
        ),
    )


def make_model(path: Path = Path("config.json")) -> SettingsModel:
    model = SettingsModel(FakeCameraEnumerator())
    model.open_profile(camera_profile(), path)
    return model


def make_actions(
    *,
    model: SettingsModel | None = None,
    controller: FakeController | None = None,
    settings_path: Path = Path("settings.json"),
    on_theme_applied=None,
    on_reload=None,
    on_status=None,
) -> tuple[AppSettingsActions, FakeController, SettingsModel]:
    controller = controller or FakeController()
    model = model or make_model()
    actions = AppSettingsActions(
        cast(SessionController, controller),
        model,
        settings_path=settings_path,
        on_theme_applied=on_theme_applied,
        on_reload=on_reload,
        on_status=on_status,
    )
    return actions, controller, model


class TestTheme:
    def test_set_theme_applies_and_persists_immediately(self, tmp_path: Path) -> None:
        applied: list[Theme] = []
        settings_path = tmp_path / "settings.json"
        actions, controller, model = make_actions(
            model=make_model(tmp_path / "config.json"),
            settings_path=settings_path,
            on_theme_applied=applied.append,
        )

        actions.set_theme(Theme.DARK)

        assert applied == [Theme.DARK]
        assert model.app_settings.theme is Theme.DARK
        assert not model.is_dirty
        assert controller.request_stop_calls == 0
        assert controller.started == []
        assert load_app_settings(settings_path).ui.theme is Theme.DARK


class TestLogLevel:
    def test_log_level_is_persisted_and_never_restarts(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        actions, controller, model = make_actions(settings_path=settings_path)

        actions.set_log_level("DEBUG")

        assert settings_path.exists()
        assert controller.log_levels == ["DEBUG"]
        assert controller.request_stop_calls == 0
        assert controller.started == []
        assert not model.is_dirty


class TestReactionTime:
    def test_reaction_time_persists_and_reloads_when_profile_exists(
        self, tmp_path: Path
    ) -> None:
        settings_path = tmp_path / "settings.json"
        reloaded: list[Path] = []
        actions, _controller, model = make_actions(
            model=make_model(tmp_path / "config.json"),
            settings_path=settings_path,
            on_reload=reloaded.append,
        )

        actions.set_reaction_time(30)

        assert settings_path.exists()
        assert reloaded == [tmp_path / "config.json"]
        assert not model.is_dirty

    def test_reaction_time_without_profile_does_not_reload(
        self, tmp_path: Path
    ) -> None:
        settings_path = tmp_path / "settings.json"
        reloaded: list[Path] = []
        model = SettingsModel(FakeCameraEnumerator())
        actions, _controller, _model = make_actions(
            model=model, settings_path=settings_path, on_reload=reloaded.append
        )

        actions.set_reaction_time(30)

        assert settings_path.exists()
        assert reloaded == []

    def test_invalid_reaction_time_does_not_reload(self, tmp_path: Path) -> None:
        reloaded: list[Path] = []
        actions, _controller, model = make_actions(
            model=make_model(tmp_path / "config.json"),
            settings_path=tmp_path / "settings.json",
            on_reload=reloaded.append,
        )

        actions.set_reaction_time(-1)

        assert reloaded == []
        assert model.app_settings.reaction_time_ms == 0
        assert "reaction time" in actions.status


class TestPersistence:
    def test_app_settings_save_failure_is_reported(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings-dir"
        settings_path.mkdir()
        statuses: list[str] = []
        actions, _controller, _model = make_actions(
            settings_path=settings_path, on_status=statuses.append
        )

        actions.set_log_level("DEBUG")

        assert "could not save app settings" in actions.status
        assert statuses and "could not save app settings" in statuses[-1]
