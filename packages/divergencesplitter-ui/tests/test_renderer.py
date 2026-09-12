"""Exercise native widget validation without opening a viewport."""

from unittest.mock import Mock

import pytest
from divergencesplitter import (
    Action,
    ConditionStatus,
    Detected,
    LiveSplitConnection,
    MeanBrightnessDetector,
    MonotonicTime,
    Rule,
    RuleSequence,
    Scenario,
)
from divergencesplitter_runtime.instances import ScenarioInstance
from divergencesplitter_runtime.metrics import RuntimeMetricsSnapshot
from divergencesplitter_runtime.observability import (
    ConditionObservation,
    build_detector_tree,
)
from divergencesplitter_ui.presentation import ObservableDiagnostics


def test_scenario_diagnostics_build_update_and_restart() -> None:
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from divergencesplitter_ui.renderer import ScreenRenderer

    condition = Detected(MeanBrightnessDetector(), 100.0)
    tree = build_detector_tree(
        (
            ScenarioInstance(
                connection=LiveSplitConnection("rpc", "event"),
                scenario=Scenario(
                    start_condition=condition,
                    reset_condition=None,
                    incomplete_condition=None,
                    splits=(),
                ),
            ),
        )
    )
    diagnostics = Mock(spec=ObservableDiagnostics)
    diagnostics.detector_tree.return_value = tree
    diagnostics.take_latest_processed_frame.return_value = None
    diagnostics.metrics_snapshot.return_value = RuntimeMetricsSnapshot(
        MonotonicTime(0), 1.0, 0.0, 0.0, 0, 0
    )

    dpg.create_context()
    try:
        renderer = ScreenRenderer()
        renderer.build()
        for _ in range(2):
            diagnostics.take_condition_observations.return_value = ()
            renderer.tick("STARTING", diagnostics)
            row = renderer._rows[0]
            assert row.score_handles is not None
            assert [dpg.get_value(handle) for handle in row.score_handles] == [
                "—",
                "—",
                "—",
            ]

            diagnostics.take_condition_observations.return_value = (
                ConditionObservation(
                    condition, ConditionStatus.TRUE, 123.5, 150.0, active=True
                ),
            )
            renderer.tick("RUNNING", diagnostics)
            assert [dpg.get_value(handle) for handle in row.score_handles] == [
                "100.0000",
                "123.5000",
                "150.0000",
            ]
            assert "ACTIVE" in dpg.get_item_label(row.condition_handle)

            renderer.tick("STOPPED", None)
            assert all(not dpg.does_item_exist(handle) for handle in row.score_handles)
    finally:
        dpg.destroy_context()


def test_active_style_propagates_to_split_rule_and_step_then_clears() -> None:
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from divergencesplitter_ui.renderer import ScreenRenderer

    first = Detected(MeanBrightnessDetector(), 0.5)
    second = Detected(MeanBrightnessDetector(), 0.7)
    tree = build_detector_tree(
        (
            ScenarioInstance(
                connection=LiveSplitConnection("rpc", "event"),
                scenario=Scenario(
                    start_condition=Detected(MeanBrightnessDetector(), 0.9),
                    reset_condition=None,
                    incomplete_condition=None,
                    splits=(
                        (Rule(first, Action("split")),),
                        (RuleSequence(Rule(second, Action("split"))),),
                    ),
                ),
            ),
        )
    )
    dpg.create_context()
    try:
        renderer = ScreenRenderer()
        renderer.build()
        renderer._build_scenario(tree.scenarios[0])
        for current in (first, second, None):
            renderer._apply_observations(
                tuple(
                    ConditionObservation(
                        condition,
                        # Old results persist after advancing to another split.
                        ConditionStatus.FALSE,
                        0.2 if condition is current else None,
                        0.3,
                        active=condition is current,
                    )
                    for condition in (first, second)
                )
            )
            for branch in renderer._branches:
                active = any(node.condition is current for node in branch.conditions)
                info = dpg.get_item_info(branch.handle)
                assert info["theme"] == (
                    renderer._active_theme if active else renderer._inactive_theme
                )
                expected_font = (
                    renderer._bold_font if active else renderer._regular_font
                )
                assert info["font"] == expected_font
                assert ("ACTIVE" in dpg.get_item_label(branch.handle)) == active
            for row in renderer._rows:
                active = row.node.condition is current
                for handle in (row.condition_handle, row.detector_handle):
                    assert handle is not None
                    info = dpg.get_item_info(handle)
                    assert info["theme"] == (
                        renderer._active_theme if active else renderer._inactive_theme
                    )
                    expected_font = (
                        renderer._bold_font if active else renderer._regular_font
                    )
                    assert info["font"] == expected_font
    finally:
        dpg.destroy_context()
