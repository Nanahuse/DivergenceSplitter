from __future__ import annotations

import inspect
from typing import cast

import flet as ft
from divergencesplitter_ui.configuration.profile_header import (
    NO_PROFILE_TEXT,
    ProfileHeader,
)


def make_header() -> ProfileHeader:
    return ProfileHeader(
        on_new=lambda event: None,
        on_open=lambda event: None,
        on_save=lambda event: None,
        on_save_as=lambda event: None,
    )


class TestProfileHeaderStatusRemoval:
    def test_has_no_status_control(self) -> None:
        header = make_header()

        assert not hasattr(header, "status")
        row = cast(ft.Row, header.control)
        keys = [getattr(control, "key", None) for control in row.controls]
        assert "profile-status" not in keys

    def test_sync_has_no_status_parameter(self) -> None:
        parameters = inspect.signature(ProfileHeader.sync).parameters

        assert "status" not in parameters


class TestProfileHeaderControls:
    def test_control_is_the_single_action_row(self) -> None:
        header = make_header()

        assert isinstance(header.control, ft.Row)
        assert header.control.controls == [
            header.profile_path,
            header.new_button,
            header.open_button,
            header.save_button,
            header.save_as_button,
        ]
        assert header.profile_path.value == NO_PROFILE_TEXT

    def test_sync_updates_path_and_buttons_only(self) -> None:
        header = make_header()

        changed = header.sync(
            path_text="profile.json *",
            new_enabled=False,
            open_enabled=True,
            save_enabled=True,
            save_as_enabled=False,
        )

        assert changed is True
        assert header.profile_path.value == "profile.json *"
        assert header.new_button.disabled is True
        assert header.open_button.disabled is False
        assert header.save_button.disabled is False
        assert header.save_as_button.disabled is True

    def test_sync_without_changes_reports_false(self) -> None:
        header = make_header()
        header.sync(
            path_text="profile.json",
            new_enabled=True,
            open_enabled=True,
            save_enabled=True,
            save_as_enabled=True,
        )

        changed = header.sync(
            path_text="profile.json",
            new_enabled=True,
            open_enabled=True,
            save_enabled=True,
            save_as_enabled=True,
        )

        assert changed is False
