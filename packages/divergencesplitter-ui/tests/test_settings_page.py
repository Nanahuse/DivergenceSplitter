from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import flet as ft
import pytest
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

    def test_states_that_apply_is_explicit(self) -> None:
        page, _model, _controller, _actions = make_page()

        labels = collect_text(page.control)
        assert "Edit the values, then select Apply to save and apply them." in labels
        assert (
            "Changes are applied immediately and saved to App Settings." not in labels
        )

    def test_apply_starts_disabled(self) -> None:
        page, _model, _controller, _actions = make_page()

        assert page.apply.disabled is True


class TestEditOnly:
    def test_reaction_time_edit_updates_draft_without_saving(
        self, tmp_path: Path
    ) -> None:
        settings_path = tmp_path / "settings.json"
        page, model, _controller, _actions = make_page(settings_path=settings_path)

        page.reaction_time.value = "30"
        fire(page._on_reaction_time_changed, page.reaction_time)

        assert model.app_settings_draft.reaction_time_text == "30"
        assert not settings_path.exists()
        assert not model.is_dirty

    def test_reaction_time_edit_does_not_restart_runtime(self, tmp_path: Path) -> None:
        controller = FakeController(SessionState.RUNNING)
        reloaded: list[Path] = []
        page, _model, _controller, _actions = make_page(
            controller=controller,
            settings_path=tmp_path / "settings.json",
            reloaded=reloaded,
        )

        page.reaction_time.value = "30"
        fire(page._on_reaction_time_changed, page.reaction_time)

        assert reloaded == []
        assert controller.request_stop_calls == 0
        assert controller.started == []

    def test_reaction_time_field_has_no_commit_handlers(self) -> None:
        page, _model, _controller, _actions = make_page()

        assert page.reaction_time.on_submit is None
        assert page.reaction_time.on_blur is None

    def test_log_level_edit_updates_draft_without_applying(
        self, tmp_path: Path
    ) -> None:
        settings_path = tmp_path / "settings.json"
        page, model, controller, _actions = make_page(settings_path=settings_path)

        page.log_level.value = "DEBUG"
        fire(page._on_log_level, page.log_level)

        assert model.app_settings_draft.log_level == "DEBUG"
        assert not settings_path.exists()
        assert controller.log_levels == []
        assert controller.started == []
        assert not model.is_dirty

    def test_theme_edit_updates_draft_without_switching_theme(
        self, tmp_path: Path
    ) -> None:
        applied: list[Theme] = []
        settings_path = tmp_path / "settings.json"
        page, model, _controller, _actions = make_page(
            settings_path=settings_path, applied=applied
        )

        page.theme.value = "dark"
        fire(page._on_theme, page.theme)

        assert model.app_settings_draft.theme is Theme.DARK
        assert model.applied_app_settings.theme is Theme.LIGHT
        assert applied == []
        assert not settings_path.exists()
        assert not model.is_dirty


class TestApplyButton:
    def test_disabled_without_changes(self) -> None:
        page, model, _controller, _actions = make_page()

        page.sync(model.app_settings_draft, edit_permission(SessionState.IDLE))

        assert page.apply.disabled is True

    def test_enabled_after_a_change(self) -> None:
        page, _model, _controller, _actions = make_page()

        page.reaction_time.value = "30"
        fire(page._on_reaction_time_changed, page.reaction_time)

        assert page.apply.disabled is False

    def test_disabled_again_after_a_successful_apply(self, tmp_path: Path) -> None:
        page, _model, _controller, _actions = make_page(
            settings_path=tmp_path / "settings.json"
        )
        page.reaction_time.value = "30"
        fire(page._on_reaction_time_changed, page.reaction_time)

        fire(page._on_apply, page.apply)

        assert page.apply.disabled is True

    @pytest.mark.parametrize("state", [SessionState.LOADING, SessionState.STOPPING])
    def test_disabled_during_a_transition_state(self, state: SessionState) -> None:
        page, model, _controller, _actions = make_page()
        page.reaction_time.value = "30"
        fire(page._on_reaction_time_changed, page.reaction_time)

        page.sync(model.app_settings_draft, edit_permission(state))

        assert page.apply.disabled is True

    def test_enabled_while_connecting(self) -> None:
        page, model, _controller, _actions = make_page()
        page.reaction_time.value = "30"
        fire(page._on_reaction_time_changed, page.reaction_time)

        page.sync(model.app_settings_draft, edit_permission(SessionState.CONNECTING))

        assert page.reaction_time.disabled is False
        assert page.apply.disabled is False

    def test_apply_persists_app_settings_once(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        page, _model, _controller, _actions = make_page(settings_path=settings_path)
        page.log_level.value = "DEBUG"
        fire(page._on_log_level, page.log_level)

        fire(page._on_apply, page.apply)

        assert load_app_settings(settings_path).log_level == "DEBUG"
        assert page.apply.disabled is True


class TestApplyRuntime:
    def test_reaction_time_apply_restarts_once(self, tmp_path: Path) -> None:
        reloaded: list[Path] = []
        controller = FakeController(SessionState.RUNNING)
        page, _model, _controller, _actions = make_page(
            controller=controller,
            settings_path=tmp_path / "settings.json",
            reloaded=reloaded,
        )
        page.reaction_time.value = "30"
        fire(page._on_reaction_time_changed, page.reaction_time)

        fire(page._on_apply, page.apply)

        assert reloaded == [Path("config.json")]

    def test_theme_only_apply_does_not_restart(self, tmp_path: Path) -> None:
        reloaded: list[Path] = []
        applied: list[Theme] = []
        controller = FakeController(SessionState.RUNNING)
        page, _model, _controller, _actions = make_page(
            controller=controller,
            settings_path=tmp_path / "settings.json",
            applied=applied,
            reloaded=reloaded,
        )
        page.theme.value = "dark"
        fire(page._on_theme, page.theme)

        fire(page._on_apply, page.apply)

        assert applied == [Theme.DARK]
        assert reloaded == []

    def test_apply_while_stopped_does_not_start_runtime(self, tmp_path: Path) -> None:
        reloaded: list[Path] = []
        controller = FakeController(SessionState.IDLE)
        page, _model, _controller, _actions = make_page(
            controller=controller,
            settings_path=tmp_path / "settings.json",
            reloaded=reloaded,
        )
        page.log_level.value = "DEBUG"
        fire(page._on_log_level, page.log_level)

        fire(page._on_apply, page.apply)

        assert reloaded == []
        assert controller.started == []


class TestApplyErrors:
    def test_invalid_reaction_time_applies_nothing_and_keeps_draft(
        self, tmp_path: Path
    ) -> None:
        applied: list[Theme] = []
        reloaded: list[Path] = []
        settings_path = tmp_path / "settings.json"
        controller = FakeController(SessionState.RUNNING)
        page, model, _controller, _actions = make_page(
            controller=controller,
            settings_path=settings_path,
            applied=applied,
            reloaded=reloaded,
        )
        page.theme.value = "dark"
        fire(page._on_theme, page.theme)
        page.reaction_time.value = "abc"
        fire(page._on_reaction_time_changed, page.reaction_time)

        fire(page._on_apply, page.apply)

        assert not settings_path.exists()
        assert applied == []
        assert reloaded == []
        assert model.applied_app_settings.theme is Theme.LIGHT
        assert model.app_settings_draft.theme is Theme.DARK
        assert model.app_settings_draft.reaction_time_text == "abc"
        assert "reaction time" in page.status.value

    def test_save_failure_keeps_draft_and_reports_error(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings-dir"
        settings_path.mkdir()
        page, model, _controller, _actions = make_page(settings_path=settings_path)
        page.log_level.value = "DEBUG"
        fire(page._on_log_level, page.log_level)

        fire(page._on_apply, page.apply)

        assert "could not save app settings" in page.status.value
        assert model.applied_app_settings.log_level == "OFF"
        assert model.app_settings_draft.log_level == "DEBUG"


class TestDraftRetention:
    def test_periodic_sync_does_not_revert_the_draft(self) -> None:
        page, model, _controller, _actions = make_page()
        page.reaction_time.value = "30"
        fire(page._on_reaction_time_changed, page.reaction_time)

        page.sync(model.app_settings_draft, edit_permission(SessionState.IDLE))

        assert page.reaction_time.value == "30"
        assert model.app_settings_draft.reaction_time_text == "30"

    def test_sync_restores_the_draft_after_a_reload(self) -> None:
        page, model, _controller, _actions = make_page()
        model.edit_theme(Theme.DARK)
        model.edit_reaction_time("30")
        page.theme.value = "light"
        page.reaction_time.value = "0"

        page.sync(model.app_settings_draft, edit_permission(SessionState.IDLE))

        assert page.theme.value == "dark"
        assert page.reaction_time.value == "30"

    def test_editing_does_not_dirty_the_profile(self) -> None:
        page, model, _controller, _actions = make_page()
        model.mark_saved()
        assert not model.is_dirty

        page.theme.value = "dark"
        fire(page._on_theme, page.theme)
        page.reaction_time.value = "30"
        fire(page._on_reaction_time_changed, page.reaction_time)

        assert not model.is_dirty


class TestNoProfile:
    def test_editable_without_profile_and_apply_works(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        page, model, controller, _actions = make_page(
            profile=False, settings_path=settings_path
        )
        page.sync(model.app_settings_draft, edit_permission(SessionState.IDLE))

        assert page.log_level.disabled is False
        assert page.reaction_time.disabled is False

        page.log_level.value = "DEBUG"
        fire(page._on_log_level, page.log_level)
        fire(page._on_apply, page.apply)

        assert load_app_settings(settings_path).log_level == "DEBUG"
        assert not model.is_dirty
        assert controller.request_stop_calls == 0
        assert controller.started == []
