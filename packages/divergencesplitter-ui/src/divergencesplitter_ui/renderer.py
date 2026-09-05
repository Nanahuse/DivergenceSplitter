"""Dear PyGui connection for the main screen.

This module is the only place that imports Dear PyGui. It owns every widget
handle, texture, GPU buffer, and the render-loop tick that drives the pure
``ScreenPresenter`` and ``image`` decisions. Everything runs on the main thread
inside Dear PyGui's render loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
from divergencesplitter_runtime.observability import (
    ConditionNode,
    DetectorNode,
    DetectorTreeSnapshot,
    RuleNode,
    ScenarioNode,
    SplitNode,
)

from divergencesplitter_ui._dpg import dpg
from divergencesplitter_ui.image import (
    TextureEvent,
    flatten,
    plan_texture,
    reference_to_rgba_float32,
    source_signature,
    to_rgba_float32,
)
from divergencesplitter_ui.presentation import (
    ExpansionEvent,
    ExpansionState,
    ObservableDiagnostics,
    ObservationIndex,
    ScreenPresenter,
    condition_label,
    detector_label,
    has_new_observations,
    scenario_label,
    view_for,
)


def _upload(rgba: np.ndarray) -> list[float]:
    """Prepare RGBA float32 data for a texture upload.

    Dear PyGui's typed stub names ``List[float]``, but its runtime accepts a
    contiguous float32 numpy buffer directly, which avoids copying megabytes of
    pixels into Python objects each frame.
    """

    return cast("list[float]", flatten(rgba))


@dataclass
class _ConditionRow:
    node: ConditionNode
    condition_handle: int | str
    detector_handle: int | str | None


@dataclass
class _ReferenceRow:
    detector: DetectorNode
    detector_handle: int | str
    toggle_handle: int | str
    handler_registry_handle: int | str
    texture_handles: list[int | str]
    display_handles: list[int | str]


class ScreenRenderer:
    """Bind presenter decisions to Dear PyGui widgets on the main thread."""

    WINDOW_TAG = "divergence-splitter"
    _TREE_TAG = "divergence-splitter-tree"
    _STATE_TAG = "divergence-splitter-state"
    _FPS_TAG = "divergence-splitter-fps"
    _IMAGE_GROUP_TAG = "divergence-splitter-image-group"
    _TEXTURE_REGISTRY_TAG = "divergence-splitter-textures"

    def __init__(self, presenter: ScreenPresenter | None = None) -> None:
        self._presenter = presenter or ScreenPresenter()
        self._bound_diagnostics: ObservableDiagnostics | None = None
        self._tree: DetectorTreeSnapshot | None = None
        self._rows: list[_ConditionRow] = []
        self._reference_rows: list[_ReferenceRow] = []
        self._expansion = ExpansionState()

        self._input_texture_tag: int | str | None = None
        self._input_image_tag: int | str | None = None
        self._input_signature = None

    def build(self) -> None:
        """Create the static widget structure once, before the render loop."""

        with dpg.window(
            tag=self.WINDOW_TAG,
            label="DivergenceSplitter",
            width=1100,
            height=800,
        ):
            dpg.add_text("State: —", tag=self._STATE_TAG)
            dpg.add_text(
                "input: — fps | processing: — fps",
                tag=self._FPS_TAG,
            )
            dpg.add_separator()
            dpg.add_text("Input frame")
            dpg.add_texture_registry(tag=self._TEXTURE_REGISTRY_TAG)
            dpg.add_group(tag=self._IMAGE_GROUP_TAG)
            dpg.add_separator()
            dpg.add_tree_node(
                tag=self._TREE_TAG,
                label="Scenario tree",
                default_open=True,
            )

    def tick(
        self,
        state: object,
        diagnostics: ObservableDiagnostics | None,
    ) -> None:
        """Run one update pass on the main thread."""

        if self._presenter.state_changed(state):
            name = getattr(state, "name", str(state))
            dpg.set_value(self._STATE_TAG, f"State: {name}")

        if diagnostics is not None and diagnostics is not self._bound_diagnostics:
            self._bind(diagnostics)

        if self._bound_diagnostics is None:
            return

        if self._tree is None:
            self._build_tree_if_ready()

        observations = self._bound_diagnostics.take_condition_observations()
        if has_new_observations(observations):
            self._apply_observations(observations)

        if self._presenter.image_due():
            frame = self._bound_diagnostics.take_latest_input_frame()
            if frame is not None:
                self._apply_image(frame)

        if self._presenter.fps_due():
            snapshot = self._bound_diagnostics.metrics_snapshot()
            dpg.set_value(
                self._FPS_TAG,
                (
                    f"input: {snapshot.input_fps:.1f} fps | "
                    f"processing: {snapshot.processing_fps:.1f} fps"
                ),
            )

    def _bind(self, diagnostics: ObservableDiagnostics) -> None:
        self._bound_diagnostics = diagnostics
        self._reset_tree()
        self._reset_input_image()
        dpg.set_value(self._FPS_TAG, "input: — fps | processing: — fps")
        self._tree = None
        self._build_tree_if_ready()

    def _build_tree_if_ready(self) -> None:
        diagnostics = self._bound_diagnostics
        if diagnostics is None:
            return
        tree = diagnostics.detector_tree()
        if tree is None:
            return
        self._tree = tree
        for scenario in tree.scenarios:
            self._build_scenario(scenario)

    def _reset_tree(self) -> None:
        for row in self._reference_rows:
            self._release_references(row)
            dpg.delete_item(row.handler_registry_handle)
        dpg.delete_item(self._TREE_TAG, children_only=True)
        self._rows = []
        self._reference_rows = []
        self._expansion = ExpansionState()

    def _build_scenario(self, scenario: ScenarioNode) -> None:
        scenario_node = dpg.add_tree_node(
            parent=self._TREE_TAG,
            label=scenario_label(scenario),
        )
        reset_node = dpg.add_tree_node(
            parent=scenario_node,
            label="Reset conditions",
        )
        for condition in scenario.reset_conditions:
            self._build_condition(reset_node, condition)
        for split in scenario.splits:
            self._build_split(scenario_node, split)

    def _build_split(self, parent: int | str, split: SplitNode) -> None:
        split_node = dpg.add_tree_node(
            parent=parent,
            label=f"Split {split.split_index}",
        )
        for rule in split.rules:
            self._build_rule(split_node, rule)

    def _build_rule(self, parent: int | str, rule: RuleNode) -> None:
        rule_node = dpg.add_tree_node(
            parent=parent,
            label=f"Rule {rule.rule_index} ({rule.action})",
        )
        self._build_condition(rule_node, rule.condition)

    def _build_condition(self, parent: int | str, node: ConditionNode) -> None:
        condition_handle = dpg.add_tree_node(parent=parent, label=node.condition_type)
        detector_handle: int | str | None = None
        if node.detector is not None:
            detector_handle = dpg.add_tree_node(
                parent=condition_handle,
                label=node.detector.detector_type,
            )
            self._build_reference(detector_handle, node.detector)
        self._rows.append(
            _ConditionRow(
                node=node,
                condition_handle=condition_handle,
                detector_handle=detector_handle,
            )
        )
        for child in node.children:
            self._build_condition(condition_handle, child)

    def _build_reference(self, parent: int | str, detector: DetectorNode) -> None:
        if not detector.reference_images:
            return
        toggle = dpg.add_button(
            parent=parent,
            label=f"Show references ({len(detector.reference_images)})",
            callback=self._on_reference_toggle,
        )
        registry = dpg.add_item_handler_registry()
        row = _ReferenceRow(
            detector=detector,
            detector_handle=parent,
            toggle_handle=toggle,
            handler_registry_handle=registry,
            texture_handles=[],
            display_handles=[],
        )
        dpg.configure_item(toggle, user_data=row)
        dpg.add_item_toggled_open_handler(
            parent=registry,
            two_way=True,
            callback=self._on_detector_toggle,
            user_data=row,
        )
        dpg.bind_item_handler_registry(parent, registry)
        self._reference_rows.append(row)

    def _on_reference_toggle(self, sender, app_data, user_data) -> None:
        row = user_data
        expanded = not self._expansion.is_expanded(row.detector_handle)
        event = self._expansion.reconcile(
            row.detector_handle,
            expanded=expanded,
            has_reference_images=bool(row.detector.reference_images),
        )
        if event is ExpansionEvent.SHOW:
            self._materialize_references(row)
        elif event is ExpansionEvent.HIDE:
            self._release_references(row)
        action = "Hide" if expanded else "Show"
        dpg.configure_item(
            row.toggle_handle,
            label=f"{action} references ({len(row.detector.reference_images)})",
        )

    def _on_detector_toggle(self, sender, app_data, user_data) -> None:
        if bool(app_data):
            return
        row = user_data
        event = self._expansion.reconcile(
            row.detector_handle,
            expanded=False,
            has_reference_images=bool(row.detector.reference_images),
        )
        if event is ExpansionEvent.HIDE:
            self._release_references(row)
            dpg.configure_item(
                row.toggle_handle,
                label=f"Show references ({len(row.detector.reference_images)})",
            )

    def _materialize_references(self, row: _ReferenceRow) -> None:
        for reference in row.detector.reference_images:
            array = reference_to_rgba_float32(reference.image)
            texture = dpg.add_raw_texture(
                array.shape[1],
                array.shape[0],
                _upload(array),
                format=dpg.mvFormat_Float_rgba,
                parent=self._TEXTURE_REGISTRY_TAG,
            )
            label = dpg.add_text(reference.label, parent=row.detector_handle)
            image = dpg.add_image(texture, parent=row.detector_handle)
            row.texture_handles.append(texture)
            row.display_handles.append(label)
            row.display_handles.append(image)

    def _release_references(self, row: _ReferenceRow) -> None:
        for item in row.display_handles:
            dpg.delete_item(item)
        for texture in row.texture_handles:
            dpg.delete_item(texture)
        row.display_handles = []
        row.texture_handles = []

    def _apply_observations(self, observations) -> None:
        index = ObservationIndex.build(observations)
        for row in self._rows:
            view = view_for(row.node, index)
            dpg.configure_item(row.condition_handle, label=condition_label(view))
            formatted_detector = detector_label(view)
            if row.detector_handle is not None and formatted_detector is not None:
                dpg.configure_item(row.detector_handle, label=formatted_detector)

    def _apply_image(self, frame) -> None:
        rgba = to_rgba_float32(frame.image)
        signature = source_signature(frame.image)
        event = plan_texture(self._input_signature, signature)
        if event is TextureEvent.UPDATE and self._input_texture_tag is not None:
            dpg.set_value(self._input_texture_tag, _upload(rgba))
            return
        if self._input_image_tag is not None:
            dpg.delete_item(self._input_image_tag)
        if self._input_texture_tag is not None:
            dpg.delete_item(self._input_texture_tag)
        self._input_texture_tag = dpg.add_dynamic_texture(
            signature.width,
            signature.height,
            _upload(rgba),
            parent=self._TEXTURE_REGISTRY_TAG,
        )
        self._input_image_tag = dpg.add_image(
            self._input_texture_tag,
            parent=self._IMAGE_GROUP_TAG,
        )
        self._input_signature = signature

    def _reset_input_image(self) -> None:
        if self._input_image_tag is not None:
            dpg.delete_item(self._input_image_tag)
        if self._input_texture_tag is not None:
            dpg.delete_item(self._input_texture_tag)
        self._input_image_tag = None
        self._input_texture_tag = None
        self._input_signature = None
