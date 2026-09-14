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
from divergencesplitter_runtime import (
    InstanceRunSnapshot,
    InstanceRuntimeState,
    InstanceStatus,
    LiveSplitRunInfo,
    LiveSplitSegmentInfo,
)
from divergencesplitter_runtime.instances import ScenarioInstance
from divergencesplitter_runtime.metrics import RuntimeMetricsSnapshot
from divergencesplitter_runtime.observability import (
    ConditionObservation,
    build_detector_tree,
)
from divergencesplitter_ui.presentation import ObservableDiagnostics


def run_info(*segments: tuple[int, str], revision: int = 1) -> LiveSplitRunInfo:
    return LiveSplitRunInfo(
        session_id=1,
        run_revision=revision,
        segments=tuple(LiveSplitSegmentInfo(index, name) for index, name in segments),
    )


def scenario_with_splits(
    split_conditions: tuple[Detected, ...],
) -> ScenarioInstance:
    return ScenarioInstance(
        connection=LiveSplitConnection("rpc", "event"),
        scenario=Scenario(
            start_condition=Detected(MeanBrightnessDetector(), -1.0),
            reset_condition=None,
            incomplete_condition=None,
            splits=tuple(
                (Rule(condition, Action("split")),) for condition in split_conditions
            ),
        ),
    )


def make_diagnostics(tree, statuses=None) -> Mock:
    diagnostics = Mock(spec=ObservableDiagnostics)
    diagnostics.detector_tree.return_value = tree
    diagnostics.instance_statuses.return_value = (
        statuses
        if statuses is not None
        else (InstanceStatus(0, InstanceRuntimeState.READY),)
    )
    diagnostics.take_latest_processed_frame.return_value = None
    diagnostics.take_latest_input_frame.return_value = None
    diagnostics.take_condition_observations.return_value = ()
    diagnostics.instance_run_infos.return_value = ()
    diagnostics.metrics_snapshot.return_value = RuntimeMetricsSnapshot(
        MonotonicTime(0), 1.0, 0.0, 0.0, 0, 0
    )
    return diagnostics


def split_labels(renderer, scenario_index: int = 0) -> list[str | None]:
    split_indices = sorted(
        split_index
        for scenario, split_index in renderer._split_rows
        if scenario == scenario_index
    )
    return [
        dpg_label(renderer._split_rows[(scenario_index, split_index)].handle)
        for split_index in split_indices
    ]


def dpg_label(handle) -> str | None:
    import dearpygui.dearpygui as _dpg

    return _dpg.get_item_label(handle)


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
        diagnostics.instance_statuses.return_value = ()
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
    diagnostics.instance_statuses.return_value = ()
    diagnostics.detector_tree.return_value = tree
    diagnostics.take_latest_processed_frame.return_value = None
    diagnostics.metrics_snapshot.return_value = RuntimeMetricsSnapshot(
        MonotonicTime(0), 1.0, 0.0, 0.0, 0, 0
    )
    diagnostics.instance_run_infos.return_value = ()

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


def test_split_labels_show_segment_names_and_fall_back() -> None:
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from divergencesplitter_ui.renderer import ScreenRenderer

    conditions = tuple(Detected(MeanBrightnessDetector(), 0.5) for _ in range(2))
    tree = build_detector_tree((scenario_with_splits(conditions),))
    diagnostics = make_diagnostics(tree)

    dpg.create_context()
    try:
        renderer = ScreenRenderer()
        renderer.build()
        renderer.tick("RUNNING", diagnostics)
        assert split_labels(renderer) == ["Split 0", "Split 1"]

        diagnostics.instance_run_infos.return_value = (
            InstanceRunSnapshot(0, run_info((0, "A"), (1, "B"))),
        )
        renderer.tick("RUNNING", diagnostics)
        assert split_labels(renderer) == ["Split 0 — A", "Split 1 — B"]

        diagnostics.instance_run_infos.return_value = (
            InstanceRunSnapshot(0, run_info((0, "A2"), (1, "B"), revision=2)),
        )
        renderer.tick("RUNNING", diagnostics)
        assert split_labels(renderer) == ["Split 0 — A2", "Split 1 — B"]

        diagnostics.instance_run_infos.return_value = (
            InstanceRunSnapshot(0, run_info((0, ""), (1, "B"))),
        )
        renderer.tick("RUNNING", diagnostics)
        assert split_labels(renderer) == ["Split 0", "Split 1 — B"]

        diagnostics.instance_run_infos.return_value = (
            InstanceRunSnapshot(0, run_info((1, "B"))),
        )
        renderer.tick("RUNNING", diagnostics)
        assert split_labels(renderer) == ["Split 0", "Split 1 — B"]

        diagnostics.instance_run_infos.return_value = ()
        renderer.tick("RUNNING", diagnostics)
        assert split_labels(renderer) == ["Split 0", "Split 1"]

        diagnostics.instance_run_infos.return_value = (
            InstanceRunSnapshot(0, run_info((0, "A"), (1, "B"))),
        )
        renderer.tick("RUNNING", diagnostics)
        assert split_labels(renderer) == ["Split 0 — A", "Split 1 — B"]
    finally:
        dpg.destroy_context()


def test_split_labels_do_not_mix_multiple_scenarios() -> None:
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from divergencesplitter_ui.renderer import ScreenRenderer

    conditions = tuple(Detected(MeanBrightnessDetector(), 0.5) for _ in range(2))
    tree = build_detector_tree(
        tuple(scenario_with_splits((condition,)) for condition in conditions)
    )
    diagnostics = make_diagnostics(
        tree,
        statuses=(
            InstanceStatus(0, InstanceRuntimeState.READY),
            InstanceStatus(1, InstanceRuntimeState.READY),
        ),
    )

    dpg.create_context()
    try:
        renderer = ScreenRenderer()
        renderer.build()
        renderer.tick("RUNNING", diagnostics)
        diagnostics.instance_run_infos.return_value = (
            InstanceRunSnapshot(0, run_info((0, "A"))),
            InstanceRunSnapshot(1, run_info((0, "B"))),
        )
        renderer.tick("RUNNING", diagnostics)

        assert split_labels(renderer, 0) == ["Split 0 — A"]
        assert split_labels(renderer, 1) == ["Split 0 — B"]
    finally:
        dpg.destroy_context()


def test_missing_split_segment_index_falls_back_to_position_label() -> None:
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from divergencesplitter_ui.renderer import ScreenRenderer

    conditions = tuple(Detected(MeanBrightnessDetector(), 0.5) for _ in range(3))
    tree = build_detector_tree((scenario_with_splits(conditions),))
    diagnostics = make_diagnostics(tree)

    dpg.create_context()
    try:
        renderer = ScreenRenderer()
        renderer.build()
        renderer.tick("RUNNING", diagnostics)
        diagnostics.instance_run_infos.return_value = (
            InstanceRunSnapshot(0, run_info((0, "A"), (1, "B"))),
        )
        renderer.tick("RUNNING", diagnostics)

        assert split_labels(renderer) == ["Split 0 — A", "Split 1 — B", "Split 2"]
    finally:
        dpg.destroy_context()


def test_active_split_keeps_segment_name_and_observation_does_not_drop_it() -> None:
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from divergencesplitter_ui.renderer import ScreenRenderer

    condition = Detected(MeanBrightnessDetector(), 0.5)
    tree = build_detector_tree((scenario_with_splits((condition,)),))
    diagnostics = make_diagnostics(tree)

    dpg.create_context()
    try:
        renderer = ScreenRenderer()
        renderer.build()
        diagnostics.take_condition_observations.return_value = (
            ConditionObservation(
                condition, ConditionStatus.TRUE, 0.8, 0.8, active=True
            ),
        )
        renderer.tick("RUNNING", diagnostics)
        branch = renderer._split_rows[(0, 0)]
        assert dpg.get_item_label(branch.handle) == "▶ Split 0  ACTIVE"

        diagnostics.take_condition_observations.return_value = ()
        diagnostics.instance_run_infos.return_value = (
            InstanceRunSnapshot(0, run_info((0, "A"))),
        )
        renderer.tick("RUNNING", diagnostics)
        assert dpg.get_item_label(branch.handle) == "▶ Split 0 — A  ACTIVE"

        diagnostics.take_condition_observations.return_value = (
            ConditionObservation(
                condition, ConditionStatus.TRUE, 0.8, 0.8, active=False
            ),
        )
        renderer.tick("RUNNING", diagnostics)
        assert dpg.get_item_label(branch.handle) == "Split 0 — A"
    finally:
        dpg.destroy_context()


def test_run_info_is_applied_after_the_tree_becomes_ready() -> None:
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from divergencesplitter_ui.renderer import ScreenRenderer

    condition = Detected(MeanBrightnessDetector(), 0.5)
    tree = build_detector_tree((scenario_with_splits((condition,)),))
    diagnostics = make_diagnostics(tree)
    diagnostics.detector_tree.return_value = None
    diagnostics.instance_run_infos.return_value = (
        InstanceRunSnapshot(0, run_info((0, "A"))),
    )

    dpg.create_context()
    try:
        renderer = ScreenRenderer()
        renderer.build()
        renderer.tick("RUNNING", diagnostics)
        assert renderer._split_rows == {}

        diagnostics.detector_tree.return_value = tree
        renderer.tick("RUNNING", diagnostics)

        assert split_labels(renderer) == ["Split 0 — A"]
    finally:
        dpg.destroy_context()


def test_run_update_does_not_rebuild_tree_or_expansion() -> None:
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from divergencesplitter_ui.renderer import ScreenRenderer

    condition = Detected(MeanBrightnessDetector(), 0.5)
    tree = build_detector_tree((scenario_with_splits((condition,)),))
    diagnostics = make_diagnostics(tree)

    dpg.create_context()
    try:
        renderer = ScreenRenderer()
        renderer.build()
        renderer.tick("RUNNING", diagnostics)
        scenario_handle = renderer._scenario_nodes[0][0]
        split_handle = renderer._split_rows[(0, 0)].handle
        dpg.set_value(scenario_handle, True)

        diagnostics.instance_run_infos.return_value = (
            InstanceRunSnapshot(0, run_info((0, "A"))),
        )
        renderer.tick("RUNNING", diagnostics)

        assert renderer._scenario_nodes[0][0] == scenario_handle
        assert renderer._split_rows[(0, 0)].handle == split_handle
        assert dpg.get_value(scenario_handle) is True
        assert dpg.get_item_label(split_handle) == "Split 0 — A"
    finally:
        dpg.destroy_context()


def test_instance_status_rows_update_without_rebuilding_tree_or_new_frames() -> None:
    from divergencesplitter_runtime import InstanceRuntimeState, InstanceStatus

    dpg = pytest.importorskip("dearpygui.dearpygui")
    from divergencesplitter_ui.renderer import ScreenRenderer

    conditions = tuple(Detected(MeanBrightnessDetector(), 0.5) for _ in range(2))
    tree = build_detector_tree(
        tuple(
            ScenarioInstance(
                LiveSplitConnection(f"rpc-{i}", f"event-{i}"),
                Scenario(condition, None, None, ()),
            )
            for i, condition in enumerate(conditions)
        )
    )
    diagnostics = Mock(spec=ObservableDiagnostics)
    diagnostics.detector_tree.return_value = tree
    diagnostics.instance_statuses.return_value = (
        InstanceStatus(0, InstanceRuntimeState.READY),
        InstanceStatus(1, InstanceRuntimeState.CONNECTING),
    )
    diagnostics.take_condition_observations.return_value = (
        ConditionObservation(
            conditions[0], ConditionStatus.TRUE, 0.8, 0.8, active=True
        ),
    )
    diagnostics.take_latest_processed_frame.return_value = None
    diagnostics.take_latest_input_frame.return_value = None
    diagnostics.metrics_snapshot.return_value = RuntimeMetricsSnapshot(
        MonotonicTime(0), 1.0, 0.0, 0.0, 0, 0
    )
    diagnostics.instance_run_infos.return_value = ()

    dpg.create_context()
    try:
        renderer = ScreenRenderer()
        renderer.build()
        renderer.tick("RUNNING", diagnostics)
        first_handle = renderer._instance_rows[0]
        second_handle = renderer._instance_rows[1]
        scenario_handle = renderer._scenario_nodes[0][0]
        dpg.set_value(scenario_handle, True)
        assert "Connected" in dpg.get_value(first_handle)
        assert "Connecting..." in dpg.get_value(second_handle)
        assert "ACTIVE" in dpg.get_item_label(renderer._rows[0].condition_handle)
        diagnostics.take_condition_observations.return_value = ()
        diagnostics.instance_statuses.return_value = (
            InstanceStatus(0, InstanceRuntimeState.CONNECTING),
            InstanceStatus(1, InstanceRuntimeState.READY),
        )
        renderer.tick("RUNNING", diagnostics)
        assert "Connecting..." in dpg.get_value(first_handle)
        assert "Connected" in dpg.get_value(second_handle)
        assert renderer._scenario_nodes[0][0] == scenario_handle
        assert dpg.get_value(scenario_handle) is True
        assert "Connecting..." in dpg.get_item_label(scenario_handle)
        assert "ACTIVE" not in dpg.get_item_label(renderer._rows[0].condition_handle)

        diagnostics.instance_statuses.return_value = (
            InstanceStatus(0, InstanceRuntimeState.READY),
            InstanceStatus(1, InstanceRuntimeState.FAILED, "split count mismatch"),
        )
        renderer.tick("RUNNING", diagnostics)
        assert "Failed" in dpg.get_value(second_handle)
        assert "split count mismatch" in dpg.get_value(second_handle)
        assert "ACTIVE" not in dpg.get_item_label(renderer._rows[0].condition_handle)

        renderer.tick("STOPPED", None)
        assert not dpg.does_item_exist(first_handle)
        assert not dpg.does_item_exist(second_handle)
        assert renderer._instance_rows == {}
    finally:
        dpg.destroy_context()
