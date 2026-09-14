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


@pytest.mark.parametrize("source_type", ["camera", "ndi"])
def test_configuration_displays_runtime_frames_for_both_sources(source_type, tmp_path):
    import numpy as np
    from divergencesplitter.frame.models import Frame
    from divergencesplitter_ui.session import SessionState
    from divergencesplitter_ui.settings import SettingsModel, SourceType

    dpg = pytest.importorskip("dearpygui.dearpygui")
    from divergencesplitter_ui.renderer import ScreenRenderer
    from divergencesplitter_ui.settings_window import ConfigurationPage

    model = SettingsModel(Mock(list_devices=Mock(return_value=[])))
    draft = model.create_default_configuration(tmp_path / "config.json")
    draft.source.selected_type = SourceType(source_type)
    controller = Mock(state=SessionState.RUNNING)
    dpg.create_context()
    page = ConfigurationPage(controller, model)
    page._ndi_discovery.refresh = Mock()
    try:
        renderer = ScreenRenderer(
            Mock(image_due=Mock(return_value=True), fps_due=Mock(return_value=False))
        )
        renderer.build()
        page.build(renderer.CONFIGURATION_PAGE_TAG)
        page._show_source_settings(draft.source.selected_type)
        diagnostics = Mock(spec=ObservableDiagnostics)
        diagnostics.detector_tree.return_value = None
        diagnostics.take_condition_observations.return_value = ()
        for value in (64, 192):
            frame = Frame(
                np.full((2, 3, 3), value, dtype=np.uint8), MonotonicTime(value)
            )
            renderer._apply_image(frame)
            page.tick(SessionState.RUNNING, runtime_frame=renderer.latest_preview_frame)
            assert dpg.does_item_exist(page._preview_image_tag)
            pixels = dpg.get_value(page._preview_texture_tag)
            assert pixels[0] == pytest.approx(value / 255)
            assert dpg.get_item_parent(page._preview_group_tag) == (
                page._ndi_settings_group
                if source_type == "ndi"
                else page._camera_settings_group
            )
        # Draft transforms update even without a new frame or Save.
        dpg.set_value(page._resize_width_tag, 1)
        dpg.set_value(page._resize_height_tag, 1)
        page._on_resize_enabled_changed(None, True, None)
        assert page._preview_signature is not None
        assert page._preview_signature.width == 1
        assert page._preview_signature.height == 1
        page._on_resize_enabled_changed(None, False, None)
        dpg.set_value(page._crop_left_tag, 1)
        page._on_crop_enabled_changed(None, True, None)
        assert page._preview_signature is not None
        assert page._preview_signature.width == 2
        assert page._preview_signature.height == 2
        assert not (tmp_path / "config.json").exists()
        controller.request_stop.assert_not_called()

        # Source edits wait for release, then rebuild the draft preview.
        page._populate = Mock()
        page._input_source_edited()
        controller.request_stop.assert_called_once()
        page.tick(SessionState.STOPPING)
        page._populate.assert_not_called()
        page.tick(SessionState.STOPPED)
        page._populate.assert_called_once_with(draft)
        renderer._reset_input_image()
        assert renderer.latest_preview_frame is None
    finally:
        page.close()
        dpg.destroy_context()


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
