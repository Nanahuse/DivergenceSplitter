"""LiveSplit connection status reaches the Monitor through the real pipeline.

The bridge is faked, but the path is real: instance status -> SessionController
aggregation -> MonitorUpdateCoordinator -> presentation -> ScenarioOverviewPanel.
"""

from __future__ import annotations

from divergencesplitter_runtime.instance_runtime import (
    InstanceRuntimeState,
    InstanceStatus,
)

from integration_tests.conftest import StartApp
from integration_tests.page import collect_text


def _monitor_text(harness) -> str:
    return collect_text(harness.monitor.control)


async def test_connecting_then_ready_is_shown_on_the_monitor(
    start_test_app: StartApp,
) -> None:
    harness = await start_test_app(with_initial_profile=True, release_on_run=False)
    await harness.wait_until(lambda: bool(harness.diagnostics_factory.created))

    await harness.wait_until(lambda: "● Connected" in _monitor_text(harness))
    assert "RUNNING" in _monitor_text(harness)

    harness.diagnostics.instances_changed(
        (InstanceStatus(0, InstanceRuntimeState.CONNECTING),)
    )

    await harness.wait_until(lambda: "● Connecting..." in _monitor_text(harness))
    await harness.wait_until(lambda: "CONNECTING" in _monitor_text(harness))

    harness.diagnostics.instances_changed(
        (InstanceStatus(0, InstanceRuntimeState.READY),)
    )

    await harness.wait_until(lambda: "● Connected" in _monitor_text(harness))
    assert "● Connecting..." not in _monitor_text(harness)
