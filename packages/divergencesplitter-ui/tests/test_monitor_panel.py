from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import cast

import flet as ft
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


def iter_controls(control: ft.Control) -> Iterator[ft.Control]:
    yield control
    for child in getattr(control, "controls", None) or ():
        yield from iter_controls(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from iter_controls(content)
    title = getattr(control, "title", None)
    if isinstance(title, ft.Control):
        yield from iter_controls(title)


def collect_text(control: ft.Control) -> list[str]:
    return [
        item.value
        for item in iter_controls(control)
        if isinstance(item, ft.Text) and isinstance(item.value, str)
    ]


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


def test_overview_uses_one_observation_read() -> None:
    monitor, diagnostics, coordinator = make_monitor()

    snapshot = coordinator.snapshot()
    assert diagnostics.take_calls == 1

    monitor.apply(snapshot)

    assert diagnostics.take_calls == 1
    overview_texts = collect_text(monitor.scenario_overview.control)
    assert any("Detected" in text for text in overview_texts)


class TestNoDiagnostics:
    def test_monitor_does_not_own_diagnostics(self) -> None:
        monitor = Monitor()

        assert not hasattr(monitor, "diagnostics")

    def test_monitor_has_no_diagnostics_control_text(self) -> None:
        monitor, _, coordinator = make_monitor()
        monitor.apply(coordinator.snapshot())

        texts = collect_text(monitor.control)
        assert "Scenario / Diagnostics" not in texts
        assert "Diagnostics" not in texts


class TestLayout:
    def test_left_column_has_no_fixed_width(self) -> None:
        monitor = Monitor()
        control = monitor.control
        assert isinstance(control, ft.Column)
        top = control.controls[0]
        assert isinstance(top, ft.Row)
        left = top.controls[0]
        assert isinstance(left, ft.Column)
        assert left.width is None

    def test_divider_follows_left_content(self) -> None:
        monitor = Monitor()
        control = monitor.control
        assert isinstance(control, ft.Column)
        top = control.controls[0]
        assert isinstance(top, ft.Row)
        assert isinstance(top.controls[1], ft.VerticalDivider)
        right = top.controls[2]
        assert isinstance(right, ft.Container)
        assert right.expand is True

    def test_overview_title_shares_the_global_status_top_edge(self) -> None:
        monitor = Monitor()
        control = monitor.control
        assert isinstance(control, ft.Column)
        top = cast(ft.Row, control.controls[0])
        left = cast(ft.Column, top.controls[0])
        right = cast(ft.Container, top.controls[2])

        # Global Status starts the left column with no inset, so the Overview
        # container must have no top padding either while keeping its other
        # insets for the scroll region.
        assert left.controls[0] is monitor.global_status.control
        padding = right.padding
        assert isinstance(padding, ft.Padding)
        assert padding.top == 0
        assert padding.left == 12
        assert padding.right == 12
        assert padding.bottom == 12

    def test_no_control_uses_the_old_fixed_width(self) -> None:
        monitor = Monitor()

        widths = [
            getattr(item, "width", None)
            for item in iter_controls(monitor.control)
            if isinstance(item, ft.Control)
        ]
        assert 560 not in widths


class TestTargetedUpdates:
    def test_controls_for_update_maps_only_changed_panels(self) -> None:
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

    def test_apply_reports_each_panel_independently(self) -> None:
        monitor, _, coordinator = make_monitor()

        update = monitor.apply(coordinator.snapshot())

        assert update.global_status is True
        assert update.scenario_overview is True
        assert update.changed is True

    def test_second_apply_reports_no_overview_change(self) -> None:
        monitor, _, coordinator = make_monitor()
        monitor.apply(coordinator.snapshot())

        update = monitor.apply(coordinator.snapshot())

        assert update.scenario_overview is False
        assert update.changed is False

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
