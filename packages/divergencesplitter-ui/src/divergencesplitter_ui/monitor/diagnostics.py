"""Scenario Diagnostics page for the Flet UI.

The page renders the pure ``DiagnosticsView`` and never reads runtime structures
itself. It is a top-level navigation page, so it fills the whole content area
and scrolls as a whole instead of living in a fixed-height Monitor section. The
body is only materialized while the page is visible: while another page is
showing, ``apply`` keeps only the latest snapshot inputs and never diffs the
large control tree. Opening the page builds the tree from the latest inputs;
leaving it releases the resident controls again. While visible the controls are
reused across observations (only text values are rewritten) and rebuilt when the
tree identity changes. Reference images are materialized into ``flet.Image``
controls only while their detector is expanded and released again on collapse,
tracked through the pure ``ExpansionState``.
"""

from __future__ import annotations

import flet as ft
from divergencesplitter_runtime.configuration.models import Theme
from divergencesplitter_runtime.instance_runtime import InstanceStatus
from divergencesplitter_runtime.observability import (
    ConditionObservation,
    DetectorTreeSnapshot,
    InstanceRunSnapshot,
)

from divergencesplitter_ui.presentation import ExpansionEvent, ExpansionState
from divergencesplitter_ui.presentation_diagnostics import (
    DiagnosticsConditionView,
    DiagnosticsConnectionView,
    DiagnosticsDetectorView,
    DiagnosticsGroupView,
    DiagnosticsRuleView,
    DiagnosticsView,
    ScenarioDiagnosticsView,
    diagnostics_view,
)
from divergencesplitter_ui.reference_image import reference_to_png_bytes
from divergencesplitter_ui.theme import (
    SemanticColors,
    instance_status_color,
    semantic_colors,
)

_INDENT_WIDTH = 18
_REFERENCE_WIDTH = 160
_REFERENCE_KEY = 0


def _set_text(control: ft.Text, value: str, *, color=None) -> bool:
    changed = False
    if control.value != value:
        control.value = value
        changed = True
    if control.color != color:
        control.color = color
        changed = True
    return changed


def _request_update(control: ft.Control) -> None:
    # A control that has not been attached to a page yet cannot be updated;
    # that is normal in headless tests and during teardown.
    try:
        control.update()
    except RuntimeError:
        return


def _indent(depth: int) -> ft.Padding:
    return ft.Padding.only(left=depth * _INDENT_WIDTH)


class _DetectorSection:
    """Detector label, scores, and lazily materialized reference images."""

    def __init__(self, view: DiagnosticsDetectorView, depth: int) -> None:
        self._view = view
        self._label = ft.Text(view.label)
        self._threshold = ft.Text(view.threshold_label)
        self._current = ft.Text(view.current_label)
        self._max = ft.Text(view.max_label)
        self._expansion = ExpansionState()
        self._gallery = ft.Column(controls=[], spacing=4)
        self._has_references = bool(view.references)
        controls: list[ft.Control] = [
            self._label,
            self._score_row("threshold", self._threshold),
            self._score_row("current", self._current),
            self._score_row("max", self._max),
        ]
        if self._has_references:
            controls.append(
                ft.ExpansionTile(
                    title=ft.Text(f"References ({len(view.references)})"),
                    controls=[self._gallery],
                    expanded=False,
                    maintain_state=True,
                    on_change=self._on_reference_change,
                )
            )
        self._root = ft.Container(
            content=ft.Column(controls=controls, spacing=2),
            padding=_indent(depth),
        )

    @staticmethod
    def _score_row(label: str, value: ft.Text) -> ft.Row:
        return ft.Row(
            controls=[ft.Text(label, width=72), value],
            spacing=8,
        )

    @property
    def control(self) -> ft.Control:
        return self._root

    def apply(self, view: DiagnosticsDetectorView) -> bool:
        self._view = view
        changed = _set_text(self._label, view.label)
        changed |= _set_text(self._threshold, view.threshold_label)
        changed |= _set_text(self._current, view.current_label)
        changed |= _set_text(self._max, view.max_label)
        return changed

    def _on_reference_change(self, event: ft.Event[ft.ExpansionTile]) -> None:
        expansion = self._expansion.reconcile(
            _REFERENCE_KEY,
            expanded=bool(event.data),
            has_reference_images=self._has_references,
        )
        if expansion is ExpansionEvent.SHOW:
            self._materialize()
        elif expansion is ExpansionEvent.HIDE:
            self.release()
        _request_update(self._gallery)

    def _materialize(self) -> None:
        if self._gallery.controls or not self._has_references:
            return
        self._gallery.controls = [
            ft.Row(
                controls=[
                    ft.Image(
                        src=reference_to_png_bytes(reference.image),
                        width=_REFERENCE_WIDTH,
                        fit=ft.BoxFit.CONTAIN,
                    ),
                    ft.Text(reference.label),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
            for reference in self._view.references
        ]

    def release(self) -> None:
        self._gallery.controls = []


class _ConditionSection:
    """One condition, its detector, and its nested children."""

    def __init__(
        self,
        view: DiagnosticsConditionView,
        depth: int,
        colors: SemanticColors,
    ) -> None:
        self._colors = colors
        self._label = ft.Text(view.label)
        self._detector = (
            None
            if view.detector is None
            else _DetectorSection(view.detector, depth + 1)
        )
        self._children = [
            _ConditionSection(child, depth + 1, colors) for child in view.children
        ]
        controls: list[ft.Control] = [self._label]
        if self._detector is not None:
            controls.append(self._detector.control)
        controls.extend(child.control for child in self._children)
        self._root = ft.Container(
            content=ft.Column(controls=controls, spacing=2),
            padding=_indent(depth),
        )

    @property
    def control(self) -> ft.Control:
        return self._root

    def apply(self, view: DiagnosticsConditionView) -> bool:
        changed = _set_text(
            self._label,
            view.label,
            color=self._colors.active if view.active else None,
        )
        if self._detector is not None and view.detector is not None:
            changed |= self._detector.apply(view.detector)
        for child_control, child_view in zip(
            self._children, view.children, strict=True
        ):
            changed |= child_control.apply(child_view)
        return changed

    def dispose(self) -> None:
        if self._detector is not None:
            self._detector.release()
        for child in self._children:
            child.dispose()


class _RuleSection:
    """A plain rule's conditions or a rule sequence's steps."""

    def __init__(
        self,
        view: DiagnosticsRuleView,
        depth: int,
        colors: SemanticColors,
    ) -> None:
        self._title = ft.Text(view.label)
        self._conditions = [
            _ConditionSection(condition, depth + 1, colors)
            for condition in view.conditions
        ]
        self._steps = [_RuleSection(step, depth + 1, colors) for step in view.steps]
        controls: list[ft.Control] = [self._title]
        controls.extend(condition.control for condition in self._conditions)
        controls.extend(step.control for step in self._steps)
        self._root = ft.Container(
            content=ft.Column(controls=controls, spacing=2),
            padding=_indent(depth),
        )

    @property
    def control(self) -> ft.Control:
        return self._root

    def apply(self, view: DiagnosticsRuleView) -> bool:
        changed = _set_text(self._title, view.label)
        for control, condition_view in zip(
            self._conditions, view.conditions, strict=True
        ):
            changed |= control.apply(condition_view)
        for control, step_view in zip(self._steps, view.steps, strict=True):
            changed |= control.apply(step_view)
        return changed

    def dispose(self) -> None:
        for condition in self._conditions:
            condition.dispose()
        for step in self._steps:
            step.dispose()


class _GroupSection:
    """Start, Reset, Incomplete, or one Split."""

    def __init__(
        self,
        view: DiagnosticsGroupView,
        depth: int,
        colors: SemanticColors,
    ) -> None:
        self._title = ft.Text(view.label, weight=ft.FontWeight.BOLD)
        self._conditions = [
            _ConditionSection(condition, depth + 1, colors)
            for condition in view.conditions
        ]
        self._rules = [_RuleSection(rule, depth + 1, colors) for rule in view.rules]
        controls: list[ft.Control] = [self._title]
        controls.extend(condition.control for condition in self._conditions)
        controls.extend(rule.control for rule in self._rules)
        self._root = ft.Container(
            content=ft.Column(controls=controls, spacing=2),
            padding=_indent(depth),
        )

    @property
    def control(self) -> ft.Control:
        return self._root

    def apply(self, view: DiagnosticsGroupView) -> bool:
        changed = _set_text(self._title, view.label)
        for control, condition_view in zip(
            self._conditions, view.conditions, strict=True
        ):
            changed |= control.apply(condition_view)
        for control, rule_view in zip(self._rules, view.rules, strict=True):
            changed |= control.apply(rule_view)
        return changed

    def dispose(self) -> None:
        for condition in self._conditions:
            condition.dispose()
        for rule in self._rules:
            rule.dispose()


class _ConnectionSection:
    """One scenario's connection status, endpoints, and error."""

    def __init__(self, view: DiagnosticsConnectionView, colors: SemanticColors) -> None:
        self._colors = colors
        self._status = ft.Text(view.status_label)
        self._rpc = ft.Text(view.rpc_endpoint)
        self._event = ft.Text(view.event_endpoint)
        self._error = ft.Text(view.error_label)
        self._root = ft.Column(
            controls=[
                ft.Text("Connection", weight=ft.FontWeight.BOLD),
                self._row("Status", self._status),
                self._row("RPC", self._rpc),
                self._row("Event", self._event),
                self._row("Error", self._error),
            ],
            spacing=2,
        )

    @staticmethod
    def _row(label: str, value: ft.Text) -> ft.Row:
        return ft.Row(
            controls=[ft.Text(label, width=72), value],
            spacing=8,
        )

    @property
    def control(self) -> ft.Control:
        return self._root

    def apply(self, view: DiagnosticsConnectionView) -> bool:
        changed = _set_text(
            self._status,
            view.status_label,
            color=instance_status_color(view.state, self._colors),
        )
        changed |= _set_text(self._rpc, view.rpc_endpoint)
        changed |= _set_text(self._event, view.event_endpoint)
        changed |= _set_text(
            self._error,
            view.error_label,
            color=self._colors.error if view.has_error else None,
        )
        return changed


class _ScenarioSection:
    """One expandable scenario with its connection and full tree."""

    def __init__(self, view: ScenarioDiagnosticsView, colors: SemanticColors) -> None:
        self._connection = _ConnectionSection(view.connection, colors)
        self._groups = [_GroupSection(group, 1, colors) for group in view.groups]
        self._tile = ft.ExpansionTile(
            title=ft.Text(view.label),
            controls=[
                self._connection.control,
                *[group.control for group in self._groups],
            ],
            expanded=False,
            maintain_state=True,
        )

    @property
    def control(self) -> ft.Control:
        return self._tile

    def apply(self, view: ScenarioDiagnosticsView) -> bool:
        changed = self._connection.apply(view.connection)
        for control, group_view in zip(self._groups, view.groups, strict=True):
            changed |= control.apply(group_view)
        return changed

    def dispose(self) -> None:
        for group in self._groups:
            group.dispose()


# The latest snapshot inputs handed over by the Monitor. They are only kept as
# references until the user expands, so no presentation model is built while the
# area is collapsed.
_DiagnosticsInputs = tuple[
    DetectorTreeSnapshot | None,
    tuple[ConditionObservation, ...],
    tuple[InstanceRunSnapshot, ...],
    tuple[InstanceStatus, ...],
]


class DiagnosticsPanel:
    """The full-height, scrollable Scenario Diagnostics page.

    The body only exists while the page is visible. ``apply`` always stores the
    latest snapshot inputs but builds or diffs nothing while another page is
    showing; opening the page materializes the view from the stored inputs and
    leaving it disposes the control tree so only the snapshot reference stays
    resident.
    """

    def __init__(self, theme: Theme = Theme.LIGHT) -> None:
        self._theme = theme
        self._colors = semantic_colors(theme)
        self._body = ft.Column(
            controls=[],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        self._control = ft.Column(
            controls=[ft.Text("Diagnostics", size=22), self._body],
            spacing=8,
            expand=True,
        )
        self._scenarios: dict[int, _ScenarioSection] = {}
        self._tree_key: object | None = None
        self._visible = False
        self._inputs: _DiagnosticsInputs | None = None

    @property
    def control(self) -> ft.Control:
        """The root control to add to the page."""

        return self._control

    @property
    def visible(self) -> bool:
        """Whether the Diagnostics page is the one currently displayed."""

        return self._visible

    def set_theme(self, theme: Theme) -> None:
        """Switch semantic colors and rebuild the resident tree when visible."""

        self._theme = theme
        self._colors = semantic_colors(theme)
        if self._visible:
            self._tree_key = None

    def apply(
        self,
        tree: DetectorTreeSnapshot | None,
        observations: tuple[ConditionObservation, ...],
        run_infos: tuple[InstanceRunSnapshot, ...],
        statuses: tuple[InstanceStatus, ...],
        *,
        visible: bool,
    ) -> bool:
        """Retain the latest snapshot and update the body only while visible.

        While hidden this only stores the inputs and releases any resident tree,
        so ``diagnostics_view`` is not called and the large control tree is not
        diffed. While visible the existing controls are reused (or rebuilt on a
        tree change) exactly as before.
        """

        self._inputs = (tree, observations, run_infos, statuses)
        if visible:
            self._visible = True
            return self._apply_view(diagnostics_view(*self._inputs))
        if self._visible:
            self._visible = False
            self._release()
        return False

    def _apply_view(self, view: DiagnosticsView) -> bool:
        if view.tree_key is not self._tree_key:
            self._rebuild(view)
            return True
        changed = False
        for scenario_view in view.scenarios:
            control = self._scenarios.get(scenario_view.scenario_index)
            if control is not None and control.apply(scenario_view):
                changed = True
        return changed

    def _release(self) -> None:
        for control in self._scenarios.values():
            control.dispose()
        self._scenarios = {}
        self._tree_key = None
        self._body.controls = []

    def _rebuild(self, view: DiagnosticsView) -> None:
        for control in self._scenarios.values():
            control.dispose()
        self._tree_key = view.tree_key
        controls = []
        self._scenarios = {}
        for scenario_view in view.scenarios:
            control = _ScenarioSection(scenario_view, self._colors)
            self._scenarios[scenario_view.scenario_index] = control
            controls.append(control.control)
        self._body.controls = controls
