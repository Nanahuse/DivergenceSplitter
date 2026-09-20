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
from divergencesplitter_ui.configuration.actions import ProfileActions
from divergencesplitter_ui.configuration.dialogs import FileDialogs
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
    def __init__(self, state: SessionState = SessionState.IDLE) -> None:
        self.state = state
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


class TestNoChanges:
    def test_apply_without_changes_writes_nothing(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        actions, controller, _model = make_actions(settings_path=settings_path)

        assert actions.apply() is True

        assert not settings_path.exists()
        assert controller.started == []
        assert controller.request_stop_calls == 0

    def test_editing_only_never_writes_or_reloads(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        reloaded: list[Path] = []
        actions, controller, model = make_actions(
            settings_path=settings_path, on_reload=reloaded.append
        )

        model.edit_theme(Theme.DARK)
        model.edit_log_level("DEBUG")
        model.edit_reaction_time("30")

        assert not settings_path.exists()
        assert reloaded == []
        assert controller.started == []
        assert controller.request_stop_calls == 0
        assert actions.status == ""


class TestThemeApply:
    def test_apply_theme_reflects_and_persists_without_restart(
        self, tmp_path: Path
    ) -> None:
        applied: list[Theme] = []
        reloaded: list[Path] = []
        settings_path = tmp_path / "settings.json"
        actions, controller, model = make_actions(
            model=make_model(tmp_path / "config.json"),
            settings_path=settings_path,
            on_theme_applied=applied.append,
            on_reload=reloaded.append,
        )
        model.edit_theme(Theme.DARK)

        assert actions.apply() is True

        assert applied == [Theme.DARK]
        assert load_app_settings(settings_path).ui.theme is Theme.DARK
        assert model.applied_app_settings.theme is Theme.DARK
        assert reloaded == []
        assert controller.started == []
        assert controller.request_stop_calls == 0
        assert not model.is_dirty

    def test_apply_without_changes_does_not_apply_theme(self, tmp_path: Path) -> None:
        applied: list[Theme] = []
        actions, _controller, _model = make_actions(
            settings_path=tmp_path / "settings.json", on_theme_applied=applied.append
        )

        assert actions.apply() is True

        assert applied == []


class TestRuntimeApply:
    def test_log_level_apply_restarts_a_running_runtime_once(
        self, tmp_path: Path
    ) -> None:
        reloaded: list[Path] = []
        settings_path = tmp_path / "settings.json"
        controller = FakeController(SessionState.RUNNING)
        actions, _controller, model = make_actions(
            controller=controller,
            model=make_model(tmp_path / "config.json"),
            settings_path=settings_path,
            on_reload=reloaded.append,
        )
        model.edit_log_level("DEBUG")

        assert actions.apply() is True

        assert reloaded == [tmp_path / "config.json"]
        assert load_app_settings(settings_path).log_level == "DEBUG"

    def test_reaction_time_apply_restarts_a_running_runtime_once(
        self, tmp_path: Path
    ) -> None:
        reloaded: list[Path] = []
        controller = FakeController(SessionState.RUNNING)
        actions, _controller, model = make_actions(
            controller=controller,
            model=make_model(tmp_path / "config.json"),
            settings_path=tmp_path / "settings.json",
            on_reload=reloaded.append,
        )
        model.edit_reaction_time("30")

        assert actions.apply() is True

        assert reloaded == [tmp_path / "config.json"]

    def test_reaction_time_and_log_level_restart_only_once(
        self, tmp_path: Path
    ) -> None:
        reloaded: list[Path] = []
        controller = FakeController(SessionState.RUNNING)
        actions, _controller, model = make_actions(
            controller=controller,
            model=make_model(tmp_path / "config.json"),
            settings_path=tmp_path / "settings.json",
            on_reload=reloaded.append,
        )
        model.edit_reaction_time("30")
        model.edit_log_level("DEBUG")

        assert actions.apply() is True

        assert reloaded == [tmp_path / "config.json"]

    def test_theme_with_runtime_change_restarts_only_once(self, tmp_path: Path) -> None:
        reloaded: list[Path] = []
        applied: list[Theme] = []
        controller = FakeController(SessionState.RUNNING)
        actions, _controller, model = make_actions(
            controller=controller,
            model=make_model(tmp_path / "config.json"),
            settings_path=tmp_path / "settings.json",
            on_theme_applied=applied.append,
            on_reload=reloaded.append,
        )
        model.edit_theme(Theme.DARK)
        model.edit_log_level("DEBUG")

        assert actions.apply() is True

        assert applied == [Theme.DARK]
        assert reloaded == [tmp_path / "config.json"]

    def test_apply_while_runtime_stopped_does_not_start_it(
        self, tmp_path: Path
    ) -> None:
        reloaded: list[Path] = []
        controller = FakeController(SessionState.IDLE)
        actions, _controller, model = make_actions(
            controller=controller,
            model=make_model(tmp_path / "config.json"),
            settings_path=tmp_path / "settings.json",
            on_reload=reloaded.append,
        )
        model.edit_reaction_time("30")
        model.edit_log_level("DEBUG")

        assert actions.apply() is True

        assert reloaded == []
        assert controller.started == []
        assert controller.request_stop_calls == 0

    def test_restart_receives_the_new_reaction_time_and_log_level(
        self, tmp_path: Path
    ) -> None:
        controller = FakeController(SessionState.RUNNING)
        profile = tmp_path / "config.json"
        model = make_model(profile)
        profile_actions = ProfileActions(
            cast(SessionController, controller),
            model,
            cast(FileDialogs, object()),
            settings_path=tmp_path / "settings.json",
        )
        actions = AppSettingsActions(
            cast(SessionController, controller),
            model,
            settings_path=tmp_path / "settings.json",
            on_reload=profile_actions.reload,
        )
        model.edit_reaction_time("30")
        model.edit_log_level("DEBUG")

        assert actions.apply() is True

        # The reload is queued behind the stop, not started immediately.
        assert controller.request_stop_calls == 1
        assert controller.started == []

        controller.state = SessionState.STOPPED
        profile_actions.advance(controller.state)

        assert controller.started == [profile]
        assert controller.started_settings[-1].reaction_time_ms == 30
        assert controller.started_settings[-1].log_level == "DEBUG"

    def test_apply_saves_once(self, tmp_path: Path, monkeypatch) -> None:
        import divergencesplitter_ui.settings.actions as actions_module

        saves: list[Path] = []
        original = actions_module.save_app_settings_document

        def counting_save(path, document):
            saves.append(path)
            return original(path, document)

        monkeypatch.setattr(actions_module, "save_app_settings_document", counting_save)
        controller = FakeController(SessionState.RUNNING)
        actions, _controller, model = make_actions(
            controller=controller,
            model=make_model(tmp_path / "config.json"),
            settings_path=tmp_path / "settings.json",
        )
        model.edit_reaction_time("30")
        model.edit_log_level("DEBUG")

        assert actions.apply() is True

        assert saves == [tmp_path / "settings.json"]


class TestApplyErrors:
    def test_invalid_reaction_time_applies_nothing(self, tmp_path: Path) -> None:
        applied: list[Theme] = []
        reloaded: list[Path] = []
        settings_path = tmp_path / "settings.json"
        controller = FakeController(SessionState.RUNNING)
        actions, _controller, model = make_actions(
            controller=controller,
            model=make_model(tmp_path / "config.json"),
            settings_path=settings_path,
            on_theme_applied=applied.append,
            on_reload=reloaded.append,
        )
        model.edit_theme(Theme.DARK)
        model.edit_reaction_time("abc")

        assert actions.apply() is False

        assert not settings_path.exists()
        assert applied == []
        assert reloaded == []
        assert model.applied_app_settings.theme is Theme.LIGHT
        assert model.applied_app_settings.reaction_time_ms == 0
        assert model.app_settings_draft.theme is Theme.DARK
        assert model.app_settings_draft.reaction_time_text == "abc"
        assert "reaction time" in actions.status

    def test_save_failure_applies_nothing(self, tmp_path: Path) -> None:
        applied: list[Theme] = []
        reloaded: list[Path] = []
        settings_path = tmp_path / "settings-dir"
        settings_path.mkdir()
        controller = FakeController(SessionState.RUNNING)
        actions, _controller, model = make_actions(
            controller=controller,
            model=make_model(tmp_path / "config.json"),
            settings_path=settings_path,
            on_theme_applied=applied.append,
            on_reload=reloaded.append,
        )
        model.edit_theme(Theme.DARK)
        model.edit_log_level("DEBUG")

        assert actions.apply() is False

        assert "could not save app settings" in actions.status
        assert applied == []
        assert reloaded == []
        assert model.applied_app_settings.theme is Theme.LIGHT
        assert model.applied_app_settings.log_level == "OFF"
        assert model.app_settings_draft.theme is Theme.DARK
        assert model.app_settings_draft.log_level == "DEBUG"

    def test_draft_is_kept_after_a_successful_apply(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        actions, _controller, model = make_actions(
            model=make_model(tmp_path / "config.json"),
            settings_path=settings_path,
        )
        model.edit_reaction_time("30")

        assert actions.apply() is True

        assert not model.app_settings_dirty
        assert model.app_settings_draft.reaction_time_text == "30"
