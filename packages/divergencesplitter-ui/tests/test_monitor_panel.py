from __future__ import annotations

import dataclasses
from typing import cast

from divergencesplitter import (
    Action,
    ConditionStatus,
    Detected,
    LiveSplitConnection,
    MeanBrightnessDetector,
    Rule,
    Scenario,
)
from divergencesplitter_runtime.instance_runtime import (
    InstanceRuntimeState,
    InstanceStatus,
)
from divergencesplitter_runtime.instances import ScenarioInstance
from divergencesplitter_runtime.observability import (
    ConditionObservation,
    DetectorTreeSnapshot,
    build_detector_tree,
)
from divergencesplitter_ui.monitor.coordinator import MonitorUpdateCoordinator
from divergencesplitter_ui.monitor.page import Monitor, MonitorUpdate
from divergencesplitter_ui.session import SessionController, SessionState


class FakeDiagnostics:
    def __init__(
        self,
        tree: DetectorTreeSnapshot,
        statuses: tuple[InstanceStatus, ...],
        run_infos: tuple,
        observations: tuple[ConditionObservation, ...],
    ) -> None:
        self.tree = tree
        self.statuses = statuses
        self.run_infos = run_infos
        self.observations = observations
        self.take_calls = 0

    def take_condition_observations(self) -> tuple[ConditionObservation, ...]:
        self.take_calls += 1
        return self.observations

    def detector_tree(self) -> DetectorTreeSnapshot:
        return self.tree

    def instance_statuses(self) -> tuple[InstanceStatus, ...]:
        return self.statuses

    def instance_run_infos(self) -> tuple:
        return self.run_infos

    def metrics_snapshot(self):
        return None


class FakeController:
    def __init__(self, diagnostics: FakeDiagnostics) -> None:
        self.state = SessionState.RUNNING
        self.diagnostics = diagnostics


def make_monitor() -> tuple[Monitor, FakeDiagnostics, MonitorUpdateCoordinator]:
    condition = Detected(MeanBrightnessDetector(), 0.9)
    instance = ScenarioInstance(
        LiveSplitConnection("tcp://rpc:0", "tcp://event:0"),
        Scenario(
            start_condition=condition,
            reset_condition=None,
            incomplete_condition=None,
            splits=((Rule(condition, Action("split")),),),
        ),
    )
    tree = build_detector_tree((instance,))
    observation = ConditionObservation(
        condition=condition,
        status=ConditionStatus.TRUE,
        latest_score=0.5,
        max_score=0.9,
        active=True,
        progress_current=0.5,
        progress_target=condition.minimum_score,
        progress_unit="score",
    )
    diagnostics = FakeDiagnostics(
        tree,
        (InstanceStatus(0, InstanceRuntimeState.READY),),
        (),
        (observation,),
    )
    coordinator = MonitorUpdateCoordinator(
        cast(SessionController, FakeController(diagnostics))
    )
    return Monitor(), diagnostics, coordinator


class TestTargetedUpdates:
    def test_controls_for_update_returns_only_changed_controls(self) -> None:
        monitor = Monitor()

        assert monitor.controls_for_update(MonitorUpdate()) == ()
        assert monitor.controls_for_update(MonitorUpdate(global_status=True)) == (
            monitor.global_status.control,
        )
        assert monitor.controls_for_update(MonitorUpdate(scenario_overview=True)) == (
            monitor.scenario_overview.control,
        )
        both = monitor.controls_for_update(
            MonitorUpdate(global_status=True, scenario_overview=True)
        )
        assert both == (
            monitor.global_status.control,
            monitor.scenario_overview.control,
        )

    def test_apply_reports_only_changed_panels(self) -> None:
        monitor, _, coordinator = make_monitor()

        update = monitor.apply(coordinator.snapshot())

        assert update.global_status is True
        assert update.scenario_overview is True
        assert update.changed is True
        monitor.apply(coordinator.snapshot())
        stable = monitor.apply(coordinator.snapshot())
        assert stable.changed is False

    def test_overview_change_targets_only_overview(self) -> None:
        monitor, diagnostics, coordinator = make_monitor()
        monitor.apply(coordinator.snapshot())
        diagnostics.observations = (
            dataclasses.replace(diagnostics.observations[0], latest_score=0.9),
        )

        update = monitor.apply(coordinator.snapshot())

        assert update.scenario_overview is True
        assert monitor.controls_for_update(update) == (
            monitor.scenario_overview.control,
        )
