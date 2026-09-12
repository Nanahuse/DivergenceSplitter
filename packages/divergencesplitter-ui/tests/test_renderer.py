"""Exercise native widget validation without opening a viewport."""

from unittest.mock import Mock

import pytest
from divergencesplitter import (
    ConditionStatus,
    Detected,
    LiveSplitConnection,
    MeanBrightnessDetector,
    MonotonicTime,
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
                ConditionObservation(condition, ConditionStatus.TRUE, 123.5, 150.0),
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
