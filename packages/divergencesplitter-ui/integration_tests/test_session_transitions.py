"""Session state transitions propagate to the real Profile controls.

The runtime status is driven through the diagnostics' public ``instances_changed``
API (the same channel ``ApplicationRuntime`` uses), so the whole
diagnostics -> SessionController.state -> FletApplication update path runs.

A ``CONNECTING`` session is active in the runtime lifecycle but still permits
editing the Profile draft, so a stalled LiveSplit connection must never block
configuration changes.
"""

from __future__ import annotations

from divergencesplitter_runtime.instance_runtime import (
    InstanceRuntimeState,
    InstanceStatus,
)
from divergencesplitter_ui.session import SessionState

from integration_tests.conftest import StartApp
from integration_tests.harness import Harness

INSTANCE_KEYS = ("profile-scenario-0", "profile-rpc-0", "profile-event-0")


def _connecting() -> tuple[InstanceStatus, ...]:
    return (InstanceStatus(0, InstanceRuntimeState.CONNECTING),)


async def _connecting_app(harness: Harness) -> None:
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    harness.diagnostics.instances_changed(_connecting())
    await harness.wait_until(
        lambda: harness.controller.state is SessionState.CONNECTING
    )


async def test_connecting_keeps_the_source_editable(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.navigate("profile")
    await harness.wait_until(lambda: not harness.disabled("profile-source-type"))

    await _connecting_app(harness)

    await harness.wait_until(lambda: not harness.disabled("profile-source-type"))


async def test_connecting_keeps_instance_editing(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.navigate("profile")
    await harness.select_tab(1)
    await harness.wait_until(lambda: not harness.disabled("profile-scenario-0"))

    await _connecting_app(harness)

    await harness.wait_until(
        lambda: all(not harness.disabled(key) for key in INSTANCE_KEYS)
    )


async def test_connecting_keeps_the_shared_header_actions(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    header = harness.header
    await harness.wait_until(lambda: header.open_button.disabled is False)

    await _connecting_app(harness)

    await harness.wait_until(
        lambda: (
            not header.open_button.disabled
            and not header.save_button.disabled
            and not header.save_as_button.disabled
        )
    )


async def test_connecting_keeps_the_settings_editable(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)

    await _connecting_app(harness)
    await harness.navigate("settings")
    await harness.wait_until(lambda: not harness.disabled("settings-reaction-time"))

    await harness.enter_text("settings-reaction-time", "30")

    await harness.wait_until(
        lambda: (
            not harness.disabled("settings-apply")
            and harness.model.app_settings_draft.reaction_time_text == "30"
        )
    )


async def test_editing_while_connecting_dirties_the_draft_without_stopping(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    await harness.navigate("profile")
    await harness.select_tab(1)

    await _connecting_app(harness)
    await harness.wait_until(lambda: not harness.disabled("profile-scenario-0"))

    await harness.enter_text("profile-scenario-0", str(harness.scenario_b))

    assert harness.model.is_dirty
    assert harness.controller.state is SessionState.CONNECTING
    assert harness.runtime_factory.runtimes[-1].request_stop_calls == 0


async def test_save_while_connecting_stops_then_restarts_with_the_saved_profile(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    harness.diagnostics.instances_changed(_connecting())
    await harness.wait_until(
        lambda: harness.controller.state is SessionState.CONNECTING
    )

    await harness.tap("profile-save")

    await harness.wait_until(
        lambda: (
            harness.controller.state is SessionState.RUNNING
            and len(harness.runtime_factory.runtimes) == 2
        )
    )
