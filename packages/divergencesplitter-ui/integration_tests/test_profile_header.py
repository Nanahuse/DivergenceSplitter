"""The shared Profile header stays current on every Current View."""

from __future__ import annotations

from divergencesplitter_ui.session import SessionState

from integration_tests.conftest import StartApp

VIEWS = ("monitor", "diagnostics", "profile", "settings", "about")


async def test_header_shows_the_profile_on_every_view(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    header = harness.header
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    await harness.wait_until(lambda: header.new_button.disabled is False)
    assert header.profile_path.value == str(harness.profile_a)

    for view in VIEWS:
        await harness.navigate(view)
        assert header.profile_path.value == str(harness.profile_a)
        assert header.new_button.disabled is False
        assert header.open_button.disabled is False
        assert header.save_button.disabled is False
        assert header.save_as_button.disabled is False


async def test_dirty_marker_and_save_state_survive_view_changes(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    header = harness.header
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    await harness.navigate("profile")
    await harness.wait_until(lambda: header.save_button.disabled is False)

    await harness.enter_text("profile-video-path", str(harness.video_b))

    await harness.wait_until(lambda: header.profile_path.value.endswith(" *"))
    assert header.save_button.disabled is False

    for view in VIEWS:
        await harness.navigate(view)
        assert header.profile_path.value == f"{harness.profile_a} *"
        assert header.save_button.disabled is False
