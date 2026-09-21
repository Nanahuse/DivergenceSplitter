"""Profile and App Settings status surface as bottom notifications."""

from __future__ import annotations

from typing import cast

import flet as ft
from divergencesplitter_ui.session import SessionState

from integration_tests.conftest import StartApp
from integration_tests.harness import Harness


def notification_messages(harness: Harness) -> list[str]:
    """Every SnackBar message the application has shown so far."""

    messages: list[str] = []
    for dialog in harness.page.dialogs:
        if (
            isinstance(dialog, ft.SnackBar)
            and isinstance(dialog.content, ft.Text)
            and isinstance(dialog.content.value, str)
        ):
            messages.append(dialog.content.value)
    return messages


async def test_saving_a_profile_shows_a_notification(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    await harness.navigate("profile")
    await harness.wait_until(lambda: harness.header.save_button.disabled is False)

    await harness.tap("profile-save")

    assert any(
        message.startswith("saved ") for message in notification_messages(harness)
    )


async def test_app_settings_error_shows_a_notification(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    await harness.navigate("settings")

    await harness.enter_text("settings-reaction-time", "abc")
    await harness.tap("settings-apply")

    assert harness.app is not None
    notification = harness.app.notification
    assert isinstance(notification, ft.SnackBar)
    assert "reaction time" in cast(ft.Text, notification.content).value


async def test_same_notification_can_be_shown_repeatedly(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    await harness.navigate("settings")

    await harness.enter_text("settings-reaction-time", "abc")
    await harness.tap("settings-apply")
    await harness.tap("settings-apply")

    messages = notification_messages(harness)
    assert messages.count("reaction time must be a non-negative integer") == 2
