from __future__ import annotations

from divergencesplitter_ui.configuration.profile_header import (
    ProfileHeader,
)


def make_header() -> ProfileHeader:
    return ProfileHeader(
        on_new=lambda event: None,
        on_open=lambda event: None,
        on_save=lambda event: None,
        on_save_as=lambda event: None,
    )


class TestProfileHeaderControls:
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
