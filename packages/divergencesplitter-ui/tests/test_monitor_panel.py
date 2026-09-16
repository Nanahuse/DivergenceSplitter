from __future__ import annotations

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
from divergencesplitter_ui.monitor.page import Monitor
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


def test_overview_and_diagnostics_share_one_observation_read() -> None:
    monitor, diagnostics, coordinator = make_monitor()

    snapshot = coordinator.snapshot()
    assert diagnostics.take_calls == 1

    monitor.apply(snapshot)

    assert diagnostics.take_calls == 1
    overview_texts = collect_text(monitor.scenario_overview.control)
    diagnostics_texts = collect_text(monitor.diagnostics.control)
    assert any("Detected" in text for text in overview_texts)
    assert any("Detected" in text for text in diagnostics_texts)
    assert any("tcp://rpc:0" in text for text in diagnostics_texts)
    assert any("0.5000" in text for text in diagnostics_texts)
