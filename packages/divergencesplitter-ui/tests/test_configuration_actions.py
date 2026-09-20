from __future__ import annotations

import asyncio
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
    VideoSourceConfiguration,
)
from divergencesplitter_runtime.configuration.profile_json import (
    load_profile,
    save_profile,
)
from divergencesplitter_ui.configuration.actions import ProfileActions
from divergencesplitter_ui.session import (
    SessionAlreadyActiveError,
    SessionController,
    SessionState,
)
from divergencesplitter_ui.settings import CameraDevice, SettingsModel

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

    def start(self, path, *, app_settings) -> None:
        if self.state in {
            SessionState.LOADING,
            SessionState.CONNECTING,
            SessionState.RUNNING,
            SessionState.STOPPING,
        }:
            raise SessionAlreadyActiveError(str(path))
        self.started.append(Path(path))
        self.started_settings.append(app_settings)
        self.state = SessionState.LOADING

    def request_stop(self) -> None:
        self.request_stop_calls += 1
        self.state = SessionState.STOPPING

    def join(self, timeout: float | None = None) -> bool:
        self.join_calls += 1
        return True

    def set_log_level(self, level: str) -> None:
        return None


class FakeDialogs:
    def __init__(
        self,
        *,
        open_result: Path | None = None,
        save_results: tuple[Path | None, ...] = (),
        confirm: bool = True,
    ) -> None:
        self.open_result = open_result
        self.save_results = list(save_results)
        self.confirm = confirm
        self.open_calls = 0
        self.save_calls = 0
        self.confirm_calls = 0

    async def open_file(self, **kwargs) -> Path | None:
        self.open_calls += 1
        return self.open_result

    async def save_file(self, **kwargs) -> Path | None:
        self.save_calls += 1
        return self.save_results.pop(0) if self.save_results else None

    async def confirm_discard(self) -> bool:
        self.confirm_calls += 1
        return self.confirm


def make_model(path: Path = Path("config.json")) -> SettingsModel:
    model = SettingsModel(FakeCameraEnumerator())
    model.open_profile(camera_profile(), path)
    return model


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


def video_profile() -> Profile:
    return Profile(
        version=1,
        source=VideoSourceConfiguration(p("run.mp4")),
        instances=(
            InstanceConfiguration(
                LiveSplitConnection("rpc", "event"), p("scenario.py")
            ),
        ),
    )


def make_actions(
    *,
    model: SettingsModel | None = None,
    dialogs: FakeDialogs | None = None,
    controller: FakeController | None = None,
    settings_path: Path = Path("settings.json"),
):
    controller = controller or FakeController()
    model = model or make_model()
    dialogs = dialogs or FakeDialogs()
    return (
        ProfileActions(
            cast(SessionController, controller),
            model,
            dialogs,
            settings_path=settings_path,
        ),
        controller,
        model,
        dialogs,
    )


class TestNew:
    def test_cancelled_save_picker_keeps_state(self) -> None:
        actions, controller, model, _dialogs = make_actions(
            dialogs=FakeDialogs(save_results=(None,))
        )

        result = asyncio.run(actions.new(SessionState.IDLE))

        assert result is False
        assert model.draft is not None
        assert model.draft.profile_path == Path("config.json")
        assert controller.started == []

    def test_new_creates_dirty_draft_at_chosen_path(self, tmp_path: Path) -> None:
        target = tmp_path / "new.json"
        actions, _, model, _ = make_actions(
            dialogs=FakeDialogs(save_results=(target,)),
            settings_path=tmp_path / "settings.json",
        )

        result = asyncio.run(actions.new(SessionState.IDLE))

        assert result is True
        assert model.draft is not None
        assert model.draft.profile_path == target
        assert model.is_dirty
        assert model.last_profile is None

    def test_dirty_draft_asks_before_discarding(self) -> None:
        model = make_model()
        model.add_instance()
        actions, _, _, dialogs = make_actions(
            model=model, dialogs=FakeDialogs(save_results=(None,), confirm=False)
        )

        result = asyncio.run(actions.new(SessionState.IDLE))

        assert result is False
        assert dialogs.confirm_calls == 1


class TestSetTheme:
    def test_set_theme_applies_and_persists_immediately(self, tmp_path: Path) -> None:
        applied: list[Theme] = []
        model = make_model(tmp_path / "config.json")
        controller = FakeController()
        settings_path = tmp_path / "settings.json"
        actions = ProfileActions(
            cast(SessionController, controller),
            model,
            FakeDialogs(),
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


class TestOpen:
    def test_valid_file_loads_and_starts(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        save_profile(path, video_profile())
        settings_path = tmp_path / "settings.json"
        actions, controller, model, _ = make_actions(
            dialogs=FakeDialogs(open_result=path), settings_path=settings_path
        )

        result = asyncio.run(actions.open(SessionState.IDLE))

        assert result is True
        assert model.draft is not None
        assert model.draft.profile_path == path
        assert controller.started == [path]
        assert model.last_profile == path
        assert settings_path.exists()

    def test_invalid_file_keeps_current_state(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.json"
        path.write_text("{ not valid json", encoding="utf-8")
        original = make_model(Path("original.json"))
        settings_path = tmp_path / "settings.json"
        actions, controller, model, _ = make_actions(
            model=original,
            dialogs=FakeDialogs(open_result=path),
            settings_path=settings_path,
        )

        result = asyncio.run(actions.open(SessionState.IDLE))

        assert result is False
        assert model.draft is not None
        assert model.draft.profile_path == Path("original.json")
        assert controller.started == []
        assert model.last_profile is None
        assert not settings_path.exists()
        assert "could not read profile" in actions.status

    def test_cancelled_picker_does_not_load(self) -> None:
        actions, _, _, _ = make_actions(dialogs=FakeDialogs(open_result=None))

        assert asyncio.run(actions.open(SessionState.IDLE)) is False


class TestSave:
    def test_save_writes_and_starts(self, tmp_path: Path) -> None:
        model = make_model(tmp_path / "config.json")
        actions, controller, _, _ = make_actions(
            model=model, settings_path=tmp_path / "settings.json"
        )

        result = asyncio.run(actions.save(SessionState.IDLE))

        assert result is True
        assert not model.is_dirty
        assert (tmp_path / "config.json").exists()
        assert controller.started == [tmp_path / "config.json"]
        assert model.last_profile == tmp_path / "config.json"

    def test_save_failure_does_not_start(self, tmp_path: Path) -> None:
        directory = tmp_path / "a-directory"
        directory.mkdir()
        model = make_model(directory)
        actions, controller, _, _ = make_actions(
            model=model, settings_path=tmp_path / "settings.json"
        )

        result = asyncio.run(actions.save(SessionState.IDLE))

        assert result is False
        assert controller.started == []
        assert "could not save" in actions.status

    def test_save_rejects_invalid_draft(self) -> None:
        model = make_model()
        model.remove_instance(0)
        actions, controller, _, _ = make_actions(model=model)

        result = asyncio.run(actions.save(SessionState.IDLE))

        assert result is False
        assert controller.started == []
        assert "at least one instance" in actions.status

    def test_save_as_updates_path_and_starts(self, tmp_path: Path) -> None:
        model = make_model(tmp_path / "first.json")
        target = tmp_path / "second.json"
        actions, controller, _, _ = make_actions(
            model=model,
            dialogs=FakeDialogs(save_results=(target,)),
            settings_path=tmp_path / "settings.json",
        )

        result = asyncio.run(actions.save_as(SessionState.IDLE))

        assert result is True
        assert model.draft is not None
        assert model.draft.profile_path == target
        assert target.exists()
        assert controller.started == [target]
        assert model.last_profile == target

    def test_cancelled_save_as_keeps_path(self, tmp_path: Path) -> None:
        model = make_model(tmp_path / "first.json")
        actions, controller, _, _ = make_actions(
            model=model,
            dialogs=FakeDialogs(save_results=(None,)),
            settings_path=tmp_path / "settings.json",
        )

        result = asyncio.run(actions.save_as(SessionState.IDLE))

        assert result is False
        assert model.draft is not None
        assert model.draft.profile_path == tmp_path / "first.json"
        assert controller.started == []


class TestReloadTiming:
    def test_reload_retries_until_terminal_session_thread_exits(self) -> None:
        class FinishingController(FakeController):
            thread_alive = True

            def start(self, path, *, app_settings) -> None:
                if self.thread_alive:
                    raise SessionAlreadyActiveError(str(path))
                super().start(path, app_settings=app_settings)

        controller = FinishingController()
        controller.state = SessionState.RUNNING
        actions, _, _, _ = make_actions(controller=controller)
        actions.reload(Path("next.json"))
        controller.state = SessionState.STOPPED

        assert actions.advance(controller.state) is False
        assert controller.started == []
        controller.thread_alive = False
        assert actions.advance(controller.state) is True
        assert controller.started == [Path("next.json")]
        assert actions.advance(controller.state) is False
        assert controller.join_calls == 0

    def test_editing_alone_does_not_start(self) -> None:
        _actions, controller, model, _ = make_actions()

        model.set_instance_scenario(0, p("other.py"))

        assert controller.started == []
        assert controller.request_stop_calls == 0
        assert model.is_dirty

    def test_save_while_running_defers_until_stopped(self, tmp_path: Path) -> None:
        model = make_model(tmp_path / "config.json")
        controller = FakeController()
        controller.state = SessionState.RUNNING
        actions, _, _, _ = make_actions(
            model=model, controller=controller, settings_path=tmp_path / "settings.json"
        )

        asyncio.run(actions.save(SessionState.RUNNING))

        assert controller.request_stop_calls == 1
        assert controller.started == []

        controller.state = SessionState.STOPPED
        assert actions.advance(controller.state) is True
        assert controller.started == [tmp_path / "config.json"]

    def test_advance_without_pending_is_noop(self) -> None:
        actions, controller, _, _ = make_actions()

        assert actions.advance(SessionState.IDLE) is False
        assert controller.started == []

    def test_reload_while_active_requests_stop(self) -> None:
        controller = FakeController()
        controller.state = SessionState.RUNNING
        actions, _, _, _ = make_actions(controller=controller)

        actions.reload(Path("config.json"))

        assert controller.request_stop_calls == 1
        assert controller.started == []
        assert actions.status == "Reloading profile..."


class TestSaveFailureWhileRunning:
    def test_failed_save_keeps_running_runtime_and_dirty(self, tmp_path: Path) -> None:
        directory = tmp_path / "a-directory"
        directory.mkdir()
        model = make_model(directory)
        model.set_instance_scenario(0, p("other.py"))
        controller = FakeController()
        controller.state = SessionState.RUNNING
        actions, _, _, _ = make_actions(
            model=model, controller=controller, settings_path=tmp_path / "settings.json"
        )

        result = asyncio.run(actions.save(SessionState.RUNNING))

        assert result is False
        assert controller.request_stop_calls == 0
        assert controller.started == []
        assert model.is_dirty


class TestNewWhileRunning:
    def test_new_defers_runtime_change_until_save(self, tmp_path: Path) -> None:
        target = tmp_path / "new.json"
        controller = FakeController()
        controller.state = SessionState.RUNNING
        actions, _, model, _ = make_actions(
            controller=controller,
            dialogs=FakeDialogs(save_results=(target,)),
            settings_path=tmp_path / "settings.json",
        )

        result = asyncio.run(actions.new(SessionState.RUNNING))

        assert result is True
        assert controller.request_stop_calls == 0
        assert controller.started == []
        assert model.draft is not None
        assert model.draft.profile_path == target
        assert model.last_profile is None


class TestOpenWhileRunning:
    def test_cancelled_open_leaves_runtime(self) -> None:
        controller = FakeController()
        controller.state = SessionState.RUNNING
        actions, _, _, _ = make_actions(
            controller=controller, dialogs=FakeDialogs(open_result=None)
        )

        assert asyncio.run(actions.open(SessionState.RUNNING)) is False
        assert controller.request_stop_calls == 0
        assert controller.started == []

    def test_invalid_open_leaves_runtime(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.json"
        path.write_text("{ not valid", encoding="utf-8")
        controller = FakeController()
        controller.state = SessionState.RUNNING
        actions, _, _, _ = make_actions(
            controller=controller,
            dialogs=FakeDialogs(open_result=path),
            settings_path=tmp_path / "settings.json",
        )

        assert asyncio.run(actions.open(SessionState.RUNNING)) is False
        assert controller.request_stop_calls == 0
        assert controller.started == []

    def test_valid_open_defers_reload_until_stopped(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        save_profile(path, video_profile())
        controller = FakeController()
        controller.state = SessionState.RUNNING
        actions, _, _, _ = make_actions(
            controller=controller,
            dialogs=FakeDialogs(open_result=path),
            settings_path=tmp_path / "settings.json",
        )

        assert asyncio.run(actions.open(SessionState.RUNNING)) is True
        assert controller.request_stop_calls == 1
        assert controller.started == []

        controller.state = SessionState.STOPPED
        assert actions.advance(controller.state) is True
        assert controller.started == [path]


class TestPermissions:
    def test_transition_state_blocks_new(self, tmp_path: Path) -> None:
        actions, _, model, dialogs = make_actions(
            dialogs=FakeDialogs(save_results=(tmp_path / "x.json",)),
            settings_path=tmp_path / "settings.json",
        )

        result = asyncio.run(actions.new(SessionState.STOPPING))

        assert result is False
        assert dialogs.save_calls == 0
        assert model.draft is not None

    def test_loaded_profile_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        save_profile(path, video_profile())
        actions, _, _model, _ = make_actions(
            dialogs=FakeDialogs(open_result=path),
            settings_path=tmp_path / "settings.json",
        )

        asyncio.run(actions.open(SessionState.IDLE))
        asyncio.run(actions.save(SessionState.IDLE))

        assert load_profile(path) == video_profile()


class TestAppSettingsOperations:
    def test_log_level_is_persisted_and_never_restarts(self, tmp_path: Path) -> None:
        model = make_model()
        settings_path = tmp_path / "settings.json"
        actions, controller, _, _ = make_actions(
            model=model, settings_path=settings_path
        )

        actions.set_log_level("DEBUG")

        assert settings_path.exists()
        assert controller.request_stop_calls == 0
        assert controller.started == []
        assert not model.is_dirty

    def test_reaction_time_persists_and_reloads_when_profile_exists(
        self, tmp_path: Path
    ) -> None:
        model = make_model(tmp_path / "config.json")
        settings_path = tmp_path / "settings.json"
        actions, controller, _, _ = make_actions(
            model=model, settings_path=settings_path
        )

        actions.commit_reaction_time(30)

        assert settings_path.exists()
        assert controller.started == [tmp_path / "config.json"]
        assert not model.is_dirty

    def test_reaction_time_without_profile_does_not_start(self, tmp_path: Path) -> None:
        model = SettingsModel(FakeCameraEnumerator())
        settings_path = tmp_path / "settings.json"
        actions, controller, _, _ = make_actions(
            model=model, settings_path=settings_path
        )

        actions.commit_reaction_time(30)

        assert settings_path.exists()
        assert controller.started == []

    def test_app_settings_save_failure_is_reported(self, tmp_path: Path) -> None:
        # A directory is not a writable settings file path.
        settings_path = tmp_path / "settings-dir"
        settings_path.mkdir()
        model = make_model()
        actions, _, _, _ = make_actions(model=model, settings_path=settings_path)

        actions.set_log_level("DEBUG")

        assert "could not save app settings" in actions.status

    def test_profile_write_succeeds_even_when_settings_write_fails(
        self, tmp_path: Path
    ) -> None:
        settings_path = tmp_path / "settings-dir"
        settings_path.mkdir()
        model = make_model(tmp_path / "config.json")
        actions, controller, model, _ = make_actions(
            model=model, settings_path=settings_path
        )

        result = asyncio.run(actions.save(SessionState.IDLE))

        assert result is True
        assert (tmp_path / "config.json").exists()
        assert controller.started == [tmp_path / "config.json"]
        assert model.draft is not None
        assert not model.is_dirty
        assert "could not save app settings" in actions.status
