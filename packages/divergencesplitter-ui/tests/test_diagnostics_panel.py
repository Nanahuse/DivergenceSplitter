from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import cast

import flet as ft
from divergencesplitter import (
    Action,
    ConditionStatus,
    Detected,
    LiveSplitConnection,
    MeanBrightnessDetector,
    RootMeanSquareSimilarityConfig,
    RootMeanSquareSimilarityDetector,
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
    build_detector_tree,
)
from divergencesplitter_ui.monitor.diagnostics import DiagnosticsPanel
from divergencesplitter_ui.presentation_diagnostics import diagnostics_view


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


def references_tile(panel: DiagnosticsPanel) -> ft.ExpansionTile:
    for item in iter_controls(panel.control):
        if (
            isinstance(item, ft.ExpansionTile)
            and isinstance(item.title, ft.Text)
            and item.title.value.startswith("References (")
        ):
            return item
    raise AssertionError("no references tile was built")


def root_tile(panel: DiagnosticsPanel) -> ft.ExpansionTile:
    control = panel.control
    assert isinstance(control, ft.ExpansionTile)
    return control


def toggle(tile: ft.ExpansionTile, expanded: bool) -> None:
    handler = cast(Callable[[ft.ControlEvent], object] | None, tile.on_change)
    assert handler is not None
    handler(cast(ft.ControlEvent, ft.Event("change", tile, data=expanded)))


def images(control: ft.Control) -> list[ft.Image]:
    return [item for item in iter_controls(control) if isinstance(item, ft.Image)]


def reference_detector() -> Detected:
    return Detected(
        RootMeanSquareSimilarityDetector(
            RootMeanSquareSimilarityConfig(((0.0, 1.0), (1.0, 0.0)))
        ),
        0.9,
    )


def instance(index: int, condition: Detected) -> ScenarioInstance:
    return ScenarioInstance(
        LiveSplitConnection(f"tcp://rpc:{index}", f"tcp://event:{index}"),
        Scenario(
            start_condition=Detected(MeanBrightnessDetector(), 0.9),
            reset_condition=None,
            incomplete_condition=None,
            splits=((Rule(condition, Action("split")),),),
        ),
    )


def observation(condition: Detected, *, latest: float = 0.5) -> ConditionObservation:
    return ConditionObservation(
        condition=condition,
        status=ConditionStatus.TRUE,
        latest_score=latest,
        max_score=0.9,
        active=True,
        progress_current=latest,
        progress_target=condition.minimum_score,
        progress_unit="score",
    )


def view_for(
    *instances: ScenarioInstance, observations: tuple = (), statuses: tuple = ()
):
    tree = build_detector_tree(tuple(instances))
    return tree, diagnostics_view(tree, observations, (), statuses)


class TestInitialState:
    def test_starts_collapsed(self) -> None:
        panel = DiagnosticsPanel()

        assert root_tile(panel).expanded is False
        assert panel.expanded is False


class TestContent:
    def test_scenario_connection_and_tree_are_rendered(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        _, view = view_for(
            instance(0, condition),
            observations=(observation(condition),),
            statuses=(InstanceStatus(0, InstanceRuntimeState.READY),),
        )
        panel = DiagnosticsPanel()

        panel.apply(view)

        texts = collect_text(panel.control)
        assert "Scenario / Diagnostics" in texts
        assert "Scenario 0" in texts
        assert "Connection" in texts
        assert "Connected" in texts
        assert "tcp://rpc:0" in texts
        assert "tcp://event:0" in texts
        assert "Start" in texts
        assert "Split 0" in texts
        assert "Rule 0 (split)" in texts

    def test_no_cross_scenario_connection_list(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        _, view = view_for(instance(0, condition), instance(1, condition))
        panel = DiagnosticsPanel()

        panel.apply(view)

        assert not any("LiveSplit" in text for text in collect_text(panel.control))


class TestReferenceLifecycle:
    def _panel_with_references(self) -> DiagnosticsPanel:
        condition = reference_detector()
        _, view = view_for(
            instance(0, condition), observations=(observation(condition),)
        )
        panel = DiagnosticsPanel()
        panel.apply(view)
        return panel

    def test_references_are_not_materialized_while_collapsed(self) -> None:
        panel = self._panel_with_references()

        assert images(references_tile(panel)) == []

    def test_expand_materializes_and_collapse_releases(self) -> None:
        panel = self._panel_with_references()
        tile = references_tile(panel)

        toggle(tile, True)
        assert len(images(tile)) == 1

        toggle(tile, False)
        assert images(tile) == []

        toggle(tile, True)
        assert len(images(tile)) == 1

    def test_observation_update_keeps_materialized_references(self) -> None:
        condition = reference_detector()
        tree, view = view_for(
            instance(0, condition), observations=(observation(condition),)
        )
        panel = DiagnosticsPanel()
        panel.apply(view)
        tile = references_tile(panel)
        toggle(tile, True)
        assert len(images(tile)) == 1

        updated = diagnostics_view(tree, (observation(condition, latest=0.7),), (), ())
        panel.apply(updated)

        assert len(images(tile)) == 1
        assert any("0.7000" in text for text in collect_text(panel.control))


class TestTreeLifecycle:
    def test_same_tree_updates_values_in_place(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        tree, view = view_for(
            instance(0, condition), observations=(observation(condition),)
        )
        panel = DiagnosticsPanel()
        panel.apply(view)

        updated = diagnostics_view(
            tree, (observation(condition, latest=0.1234),), (), ()
        )
        changed = panel.apply(updated)

        assert changed is True
        texts = collect_text(panel.control)
        assert any("0.1234" in text for text in texts)
        assert not any("0.5000" in text for text in texts)

    def test_new_tree_removes_old_scenarios(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        _, two = view_for(instance(0, condition), instance(1, condition))
        _, one = view_for(instance(0, condition))
        panel = DiagnosticsPanel()
        panel.apply(two)
        assert "Scenario 1" in collect_text(panel.control)

        changed = panel.apply(one)

        assert changed is True
        texts = collect_text(panel.control)
        assert "Scenario 0" in texts
        assert "Scenario 1" not in texts

    def test_new_tree_adds_scenarios(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        _, one = view_for(instance(0, condition))
        _, three = view_for(
            instance(0, condition), instance(1, condition), instance(2, condition)
        )
        panel = DiagnosticsPanel()
        panel.apply(one)

        panel.apply(three)

        texts = collect_text(panel.control)
        assert "Scenario 0" in texts
        assert "Scenario 1" in texts
        assert "Scenario 2" in texts


class TestShouldUpdate:
    def test_collapsed_skips_unchanged_tree(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        tree, view = view_for(instance(0, condition))
        panel = DiagnosticsPanel()

        assert panel.should_update(tree) is True
        panel.apply(view)
        assert panel.should_update(tree) is False

    def test_new_tree_requests_update(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        tree, view = view_for(instance(0, condition))
        other_tree, _ = view_for(instance(0, condition))
        panel = DiagnosticsPanel()
        panel.apply(view)

        assert panel.should_update(other_tree) is True
        assert panel.should_update(None) is True
        assert tree is not other_tree

    def test_expanded_always_requests_update(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        tree, view = view_for(instance(0, condition))
        panel = DiagnosticsPanel()
        panel.apply(view)

        toggle(root_tile(panel), True)

        assert panel.expanded is True
        assert panel.should_update(tree) is True
