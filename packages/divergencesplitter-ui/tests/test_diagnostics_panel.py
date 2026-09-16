from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import cast

import flet as ft
import pytest
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
    DetectorTreeSnapshot,
    InstanceRunSnapshot,
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


def body(panel: DiagnosticsPanel) -> ft.Column:
    control = panel.control
    assert isinstance(control, ft.Column)
    content = control.controls[1]
    assert isinstance(content, ft.Column)
    return content


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


def tree_for(*instances: ScenarioInstance) -> DetectorTreeSnapshot:
    return build_detector_tree(tuple(instances))


def apply_inputs(
    panel: DiagnosticsPanel,
    tree: DetectorTreeSnapshot | None,
    observations: tuple[ConditionObservation, ...] = (),
    statuses: tuple[InstanceStatus, ...] = (),
    *,
    visible: bool,
) -> bool:
    return panel.apply(tree, observations, (), statuses, visible=visible)


class TestInitialState:
    def test_starts_hidden_with_no_body(self) -> None:
        panel = DiagnosticsPanel()

        assert panel.visible is False
        assert body(panel).controls == []
        assert collect_text(panel.control) == ["Diagnostics"]


class TestLazyMaterialization:
    def test_hidden_does_not_materialize(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        tree = tree_for(instance(0, condition))

        panel = DiagnosticsPanel()
        apply_inputs(
            panel,
            tree,
            (observation(condition),),
            (InstanceStatus(0, InstanceRuntimeState.READY),),
            visible=False,
        )

        assert panel.visible is False
        assert body(panel).controls == []
        texts = collect_text(panel.control)
        assert "Scenario 0" not in texts
        assert "Connection" not in texts
        assert "Detected" not in texts

    def test_diagnostics_view_is_not_built_while_hidden(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        tree = tree_for(instance(0, condition))
        calls: list[int] = []

        def spy(
            tree: DetectorTreeSnapshot | None,
            observations: tuple[ConditionObservation, ...],
            run_infos: tuple[InstanceRunSnapshot, ...],
            statuses: tuple[InstanceStatus, ...],
        ) -> object:
            calls.append(1)
            return diagnostics_view(tree, observations, run_infos, statuses)

        monkeypatch.setattr(
            "divergencesplitter_ui.monitor.diagnostics.diagnostics_view", spy
        )

        panel = DiagnosticsPanel()
        apply_inputs(panel, tree, (observation(condition),), visible=False)
        assert calls == []

        apply_inputs(panel, tree, (observation(condition),), visible=True)
        assert len(calls) == 1

    def test_tree_change_while_hidden_does_not_materialize(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        tree_a = tree_for(instance(0, condition))
        tree_b = tree_for(instance(0, condition), instance(1, condition))

        panel = DiagnosticsPanel()
        apply_inputs(panel, tree_a, (observation(condition),), visible=False)
        assert body(panel).controls == []

        apply_inputs(panel, tree_b, (observation(condition),), visible=False)

        assert body(panel).controls == []
        assert collect_text(panel.control) == ["Diagnostics"]

    def test_show_materializes_full_tree(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        tree = tree_for(instance(0, condition))
        panel = DiagnosticsPanel()
        apply_inputs(
            panel,
            tree,
            (observation(condition),),
            (InstanceStatus(0, InstanceRuntimeState.READY),),
            visible=True,
        )

        assert panel.visible is True
        assert body(panel).controls != []
        texts = collect_text(panel.control)
        assert "Diagnostics" in texts
        assert "Scenario 0" in texts
        assert "Connection" in texts
        assert "Connected" in texts
        assert "tcp://rpc:0" in texts
        assert "tcp://event:0" in texts
        assert "Start" in texts
        assert "Split 0" in texts
        assert "Rule 0 (split)" in texts
        assert any("Detected" in text for text in texts)

    def test_show_uses_latest_snapshot(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        tree = tree_for(instance(0, condition))
        panel = DiagnosticsPanel()
        apply_inputs(
            panel, tree, (observation(condition, latest=0.1111),), visible=False
        )
        apply_inputs(
            panel, tree, (observation(condition, latest=0.7777),), visible=False
        )

        apply_inputs(
            panel, tree, (observation(condition, latest=0.7777),), visible=True
        )

        texts = collect_text(panel.control)
        assert any("0.7777" in text for text in texts)
        assert not any("0.1111" in text for text in texts)

    def test_hide_discards_body(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        tree = tree_for(instance(0, condition))
        panel = DiagnosticsPanel()
        apply_inputs(panel, tree, (observation(condition),), visible=True)
        assert body(panel).controls != []

        apply_inputs(panel, tree, (observation(condition),), visible=False)

        assert panel.visible is False
        assert body(panel).controls == []
        assert collect_text(panel.control) == ["Diagnostics"]

    def test_reshow_rebuilds_from_latest(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        tree = tree_for(instance(0, condition))
        panel = DiagnosticsPanel()
        apply_inputs(
            panel, tree, (observation(condition, latest=0.1111),), visible=True
        )
        apply_inputs(
            panel, tree, (observation(condition, latest=0.1111),), visible=False
        )

        apply_inputs(
            panel, tree, (observation(condition, latest=0.8888),), visible=True
        )

        texts = collect_text(panel.control)
        assert any("0.8888" in text for text in texts)
        assert not any("0.1111" in text for text in texts)

    def test_visible_updates_in_place(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        tree = tree_for(instance(0, condition))
        panel = DiagnosticsPanel()
        apply_inputs(
            panel, tree, (observation(condition, latest=0.5000),), visible=True
        )

        changed = apply_inputs(
            panel, tree, (observation(condition, latest=0.1234),), visible=True
        )

        assert changed is True
        texts = collect_text(panel.control)
        assert any("0.1234" in text for text in texts)
        assert not any("0.5000" in text for text in texts)


class TestContent:
    def test_no_cross_scenario_connection_list(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        tree = tree_for(instance(0, condition), instance(1, condition))
        panel = DiagnosticsPanel()
        apply_inputs(panel, tree, visible=True)

        assert not any("LiveSplit" in text for text in collect_text(panel.control))


class TestReferenceLifecycle:
    def _panel_with_references(self) -> DiagnosticsPanel:
        condition = reference_detector()
        tree = tree_for(instance(0, condition))
        panel = DiagnosticsPanel()
        apply_inputs(panel, tree, (observation(condition),), visible=True)
        return panel

    def test_references_are_not_materialized_until_their_detector_expands(
        self,
    ) -> None:
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
        tree = tree_for(instance(0, condition))
        panel = DiagnosticsPanel()
        apply_inputs(panel, tree, (observation(condition),), visible=True)
        tile = references_tile(panel)
        toggle(tile, True)
        assert len(images(tile)) == 1

        apply_inputs(panel, tree, (observation(condition, latest=0.7),), visible=True)

        assert len(images(tile)) == 1
        assert any("0.7000" in text for text in collect_text(panel.control))


class TestTreeLifecycle:
    def test_same_tree_updates_values_in_place(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        tree = tree_for(instance(0, condition))
        panel = DiagnosticsPanel()
        apply_inputs(panel, tree, (observation(condition),), visible=True)

        changed = apply_inputs(
            panel, tree, (observation(condition, latest=0.1234),), visible=True
        )

        assert changed is True
        texts = collect_text(panel.control)
        assert any("0.1234" in text for text in texts)
        assert not any("0.5000" in text for text in texts)

    def test_new_tree_removes_old_scenarios(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        two = tree_for(instance(0, condition), instance(1, condition))
        one = tree_for(instance(0, condition))
        panel = DiagnosticsPanel()
        apply_inputs(panel, two, visible=True)
        assert "Scenario 1" in collect_text(panel.control)

        changed = apply_inputs(panel, one, visible=True)

        assert changed is True
        texts = collect_text(panel.control)
        assert "Scenario 0" in texts
        assert "Scenario 1" not in texts

    def test_new_tree_adds_scenarios(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        one = tree_for(instance(0, condition))
        three = tree_for(
            instance(0, condition), instance(1, condition), instance(2, condition)
        )
        panel = DiagnosticsPanel()
        apply_inputs(panel, one, visible=True)

        apply_inputs(panel, three, visible=True)

        texts = collect_text(panel.control)
        assert "Scenario 0" in texts
        assert "Scenario 1" in texts
        assert "Scenario 2" in texts

    def test_tree_change_while_visible_rebuilds(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        one = tree_for(instance(0, condition))
        two = tree_for(instance(0, condition), instance(1, condition))
        panel = DiagnosticsPanel()
        apply_inputs(panel, one, visible=True)

        changed = apply_inputs(panel, two, visible=True)

        assert changed is True
        assert "Scenario 1" in collect_text(panel.control)

    def test_tree_change_while_hidden_releases_body(self) -> None:
        condition = Detected(MeanBrightnessDetector(), 0.9)
        one = tree_for(instance(0, condition))
        two = tree_for(instance(0, condition), instance(1, condition))
        panel = DiagnosticsPanel()
        apply_inputs(panel, one, visible=True)
        assert body(panel).controls != []

        apply_inputs(panel, two, visible=False)

        assert body(panel).controls == []
