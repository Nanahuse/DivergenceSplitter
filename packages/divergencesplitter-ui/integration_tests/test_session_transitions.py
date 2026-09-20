"""Session state transitions propagate to the real Profile controls.

The runtime status is driven through the diagnostics' public ``instances_changed``
API (the same channel ``ApplicationRuntime`` uses), so the whole
diagnostics -> SessionController.state -> FletApplication update path runs.
"""

from __future__ import annotations

from divergencesplitter_runtime.instance_runtime import (
    InstanceRuntimeState,
    InstanceStatus,
)
from divergencesplitter_ui.session import SessionState

from integration_tests.conftest import StartApp

INSTANCE_KEYS = ("profile-scenario-0", "profile-rpc-0", "profile-event-0")


def _connecting() -> tuple[InstanceStatus, ...]:
    return (InstanceStatus(0, InstanceRuntimeState.CONNECTING),)


def _ready() -> tuple[InstanceStatus, ...]:
    return (InstanceStatus(0, InstanceRuntimeState.READY),)


async def test_connecting_disables_the_source_and_running_restores_it(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)

    await harness.navigate("profile")
    await harness.wait_until(lambda: not harness.disabled("profile-source-type"))

    harness.diagnostics.instances_changed(_connecting())

    await harness.wait_until(
        lambda: harness.controller.state is SessionState.CONNECTING
    )
    await harness.wait_until(lambda: harness.disabled("profile-source-type"))

    harness.diagnostics.instances_changed(_ready())

    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    await harness.wait_until(lambda: not harness.disabled("profile-source-type"))


async def test_connecting_disables_instance_editing_and_running_restores_it(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)

    await harness.navigate("profile")
    await harness.select_tab(1)
    await harness.wait_until(lambda: not harness.disabled("profile-scenario-0"))

    harness.diagnostics.instances_changed(_connecting())

    await harness.wait_until(
        lambda: harness.controller.state is SessionState.CONNECTING
    )
    await harness.wait_until(
        lambda: all(harness.disabled(key) for key in INSTANCE_KEYS)
    )

    harness.diagnostics.instances_changed(_ready())

    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    await harness.wait_until(
        lambda: all(not harness.disabled(key) for key in INSTANCE_KEYS)
    )


async def test_connecting_also_disables_the_shared_header_actions(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.wait_until(lambda: harness.controller.state is SessionState.RUNNING)
    header = harness.header
    await harness.wait_until(lambda: header.open_button.disabled is False)

    harness.diagnostics.instances_changed(_connecting())

    await harness.wait_until(
        lambda: (
            header.open_button.disabled
            and header.save_button.disabled
            and header.save_as_button.disabled
        )
    )

    harness.diagnostics.instances_changed(_ready())

    await harness.wait_until(lambda: header.open_button.disabled is False)
