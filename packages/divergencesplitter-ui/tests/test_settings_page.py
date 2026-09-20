from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import flet as ft
from divergencesplitter import LiveSplitConnection
from divergencesplitter_runtime.configuration.app_settings_json import (
    load_app_settings,
)
from divergencesplitter_runtime.configuration.models import (
    CameraBackend,
    CameraDeviceConfiguration,
    CameraModeConfiguration,
    CameraSourceConfiguration,
    InstanceConfiguration,
    Profile,
    Theme,
)
from divergencesplitter_ui.session import SessionController, SessionState
from divergencesplitter_ui.settings import (
    CameraDevice,
    SettingsModel,
    edit_permission,
)
from divergencesplitter_ui.settings.actions import AppSettingsActions
from divergencesplitter_ui.settings.page import SettingsPage

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
        self.request_stop_calls = 0
        self.join_calls = 0
        self.log_levels: list[str] = []

    def start(self, path, *, app_settings) -> None:
        self.started.append(Path(path))

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


def make_page(
    *,
    profile: bool = True,
    controller: FakeController | None = None,
    settings_path: Path | None = None,
    applied: list[Theme] | None = None,
    reloaded: list[Path] | None = None,
) -> tuple[SettingsPage, SettingsModel, FakeController, AppSettingsActions]:
    controller = controller or FakeController()
    model = SettingsModel(FakeCameraEnumerator())
    if profile:
        model.open_profile(camera_profile(), Path("config.json"))
    applied = applied if applied is not None else []
    reloaded = reloaded if reloaded is not None else []
    actions = AppSettingsActions(
        cast(SessionController, controller),
        model,
        settings_path=settings_path or Path("settings.json"),
        on_theme_applied=applied.append,
        on_reload=reloaded.append,
    )
    page = SettingsPage(model, actions)
    return page, model, controller, actions


def fire(handler, control, data=None) -> None:
    handler(ft.Event("change", control, data=data))


def collect_text(control: ft.Control) -> list[str]:
    found: list[str] = []
    stack = [control]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            found.append(item)
            continue
        for attribute in ("value", "label", "content"):
            candidate = getattr(item, attribute, None)
            if isinstance(candidate, str):
                found.append(candidate)
        stack.extend(getattr(item, "controls", None) or ())
        content = getattr(item, "content", None)
        if content is not None:
            stack.append(content)
    return found


class TestBuild:
    def test_shows_application_settings_title(self) -> None:
        page, _model, _controller, _actions = make_page()

        assert "Application Settings" in collect_text(page.control)

    def test_states_that_every_change_applies_immediately(self) -> None:
        page, _model, _controller, _actions = make_page()

        labels = collect_text(page.control)
        assert "Changes are applied immediately and saved to App Settings." in labels
        assert "Theme is saved to App Settings immediately." not in labels


class TestThemeSelection:
    def test_dropdown_lists_light_and_dark_and_defaults_to_light(self) -> None:
        page, _model, _controller, _actions = make_page()

        labels = [option.text or option.key for option in page.theme.options]

        assert labels == ["Light", "Dark"]
        assert page.theme.value == "light"

    def test_dropdown_applies_theme_immediately(self, tmp_path: Path) -> None:
        applied: list[Theme] = []
        page, model, _controller, _actions = make_page(
            settings_path=tmp_path / "settings.json", applied=applied
        )

        page.theme.value = "dark"
        fire(page._on_theme, page.theme)

        assert model.app_settings.theme is Theme.DARK
        assert applied == [Theme.DARK]
        assert not model.is_dirty

    def test_theme_is_persisted_without_saving_a_profile(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        page, _model, _controller, _actions = make_page(
            profile=False, settings_path=settings_path
        )

        page.theme.value = "dark"
        fire(page._on_theme, page.theme)

        assert load_app_settings(settings_path).ui.theme is Theme.DARK

    def test_theme_change_does_not_restart_the_runtime(self, tmp_path: Path) -> None:
        controller = FakeController()
        page, _model, _controller, _actions = make_page(
            controller=controller, settings_path=tmp_path / "settings.json"
        )

        page.theme.value = "dark"
        fire(page._on_theme, page.theme)

        assert controller.request_stop_calls == 0
        assert controller.started == []

    def test_transition_state_disables_the_theme_dropdown(self) -> None:
        page, model, _controller, _actions = make_page()

        page.sync(model.app_settings, edit_permission(SessionState.CONNECTING))

        assert page.theme.disabled is True


class TestLogLevel:
    def test_applies_live_without_restart(self, tmp_path: Path) -> None:
        controller = FakeController()
        page, model, _controller, _actions = make_page(
            controller=controller, settings_path=tmp_path / "settings.json"
        )

        page.log_level.value = "DEBUG"
        fire(page._on_log_level, page.log_level)

        assert model.app_settings.log_level == "DEBUG"
        assert controller.log_levels == ["DEBUG"]
        assert not model.is_dirty
        assert controller.request_stop_calls == 0
        assert controller.started == []


class TestReactionTime:
    def test_commit_reloads_running_profile(self, tmp_path: Path) -> None:
        reloaded: list[Path] = []
        page, model, _controller, _actions = make_page(
            settings_path=tmp_path / "settings.json", reloaded=reloaded
        )

        page.reaction_time.value = "30"
        fire(page._on_reaction_time_committed, page.reaction_time)

        assert model.app_settings.reaction_time_ms == 30
        assert not model.is_dirty
        assert reloaded == [Path("config.json")]

    def test_invalid_reaction_time_does_not_reload(self, tmp_path: Path) -> None:
        reloaded: list[Path] = []
        page, model, _controller, _actions = make_page(
            settings_path=tmp_path / "settings.json", reloaded=reloaded
        )

        page.reaction_time.value = "abc"
        fire(page._on_reaction_time_committed, page.reaction_time)

        assert reloaded == []
        assert model.app_settings.reaction_time_ms == 0


class TestNoProfile:
    def test_editable_without_profile(self, tmp_path: Path) -> None:
        reloaded: list[Path] = []
        page, model, controller, _actions = make_page(
            profile=False,
            settings_path=tmp_path / "settings.json",
            reloaded=reloaded,
        )
        page.sync(model.app_settings, edit_permission(SessionState.IDLE))

        assert page.log_level.disabled is False
        assert page.reaction_time.disabled is False

        page.log_level.value = "DEBUG"
        fire(page._on_log_level, page.log_level)
        page.reaction_time.value = "50"
        fire(page._on_reaction_time_committed, page.reaction_time)

        assert model.app_settings.log_level == "DEBUG"
        assert model.app_settings.reaction_time_ms == 50
        assert not model.is_dirty
        assert controller.request_stop_calls == 0
        assert controller.started == []
        assert reloaded == []
