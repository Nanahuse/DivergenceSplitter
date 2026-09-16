"""Pure Scenario / Diagnostics presentation model for the Monitor.

Builds immutable view values from the same ``MonitorSnapshot`` the Scenario
Overview consumes: the detector tree, condition observations, run info, and
instance statuses. Nothing here imports a GUI framework, and observations are
joined to the tree by identity exactly once, reusing ``presentation`` helpers so
the Diagnostics never re-interprets runtime structures itself.

Unlike the Overview, Diagnostics keeps the full static tree (every split, rule,
sequence step, and inactive condition) and reports detailed detector and
connection information per scenario.
"""

from __future__ import annotations

from dataclasses import dataclass

from divergencesplitter.detector.models import FrozenConfigImage
from divergencesplitter_runtime.instance_runtime import (
    InstanceRuntimeState,
    InstanceStatus,
)
from divergencesplitter_runtime.livesplit.models import LiveSplitRunInfo
from divergencesplitter_runtime.observability import (
    ConditionNode,
    ConditionObservation,
    DetectorNode,
    DetectorTreeSnapshot,
    InstanceRunSnapshot,
    RuleNode,
    RuleSequenceNode,
    ScenarioNode,
)

from divergencesplitter_ui.presentation import (
    ConditionView,
    ObservationIndex,
    condition_progress_label,
    detector_label,
    format_score,
    instance_state_label,
    split_label,
    view_for,
)

NO_ERROR_LABEL = "—"
START_GROUP_LABEL = "Start"
RESET_GROUP_LABEL = "Reset"
INCOMPLETE_GROUP_LABEL = "Incomplete"
START_KIND = "start"
RESET_KIND = "reset"
INCOMPLETE_KIND = "incomplete"
SPLIT_KIND = "split"


@dataclass(frozen=True)
class ReferenceImageView:
    """One labeled reference image handed to the Flet Image control."""

    label: str
    image: FrozenConfigImage


@dataclass(frozen=True)
class DiagnosticsDetectorView:
    """Detector identity, scores, and reference images for one condition."""

    label: str
    detector_type: str
    threshold_label: str
    current_label: str
    max_label: str
    references: tuple[ReferenceImageView, ...]


@dataclass(frozen=True)
class DiagnosticsConditionView:
    """One condition and its nested children in the full display tree."""

    label: str
    active: bool
    detector: DiagnosticsDetectorView | None
    children: tuple[DiagnosticsConditionView, ...]


@dataclass(frozen=True)
class DiagnosticsRuleView:
    """A plain rule (``conditions``) or a rule sequence (``steps``)."""

    label: str
    conditions: tuple[DiagnosticsConditionView, ...]
    steps: tuple[DiagnosticsRuleView, ...]


@dataclass(frozen=True)
class DiagnosticsGroupView:
    """Start, Reset, Incomplete, or one Split's rules."""

    kind: str
    label: str
    conditions: tuple[DiagnosticsConditionView, ...]
    rules: tuple[DiagnosticsRuleView, ...]


@dataclass(frozen=True)
class DiagnosticsConnectionView:
    """One scenario's LiveSplit destination and connection outcome."""

    state: InstanceRuntimeState | None
    status_label: str
    rpc_endpoint: str
    event_endpoint: str
    error_label: str
    has_error: bool


@dataclass(frozen=True)
class ScenarioDiagnosticsView:
    """Everything Diagnostics shows for one scenario."""

    scenario_index: int
    label: str
    connection: DiagnosticsConnectionView
    groups: tuple[DiagnosticsGroupView, ...]


@dataclass(frozen=True)
class DiagnosticsView:
    """The full Diagnostics model plus the tree identity it was built from.

    ``tree_key`` is the source ``DetectorTreeSnapshot`` object (or ``None``).
    Its identity is stable for the life of one session and changes when the
    runtime rebuilds the tree, letting the control reuse controls while the tree
    is unchanged and rebuild when it is not.
    """

    tree_key: object | None
    scenarios: tuple[ScenarioDiagnosticsView, ...]


def _condition_label(view: ConditionView) -> str:
    """Format one condition line with status, progress, and the ACTIVE marker.

    Detector scores are omitted here because the detector section already shows
    threshold/current/max; every other condition falls back to the shared
    progress formatter so Hold, Elapsed, Nth, and Then keep their progress.
    """

    marker = "▶ " if view.active else ""
    active = "  ACTIVE" if view.active else ""
    detail = "" if view.detector_type is not None else condition_progress_label(view)
    suffix = f"  {detail}" if detail else ""
    return f"{marker}{view.condition_type} [{view.status_label}]{suffix}{active}"


def _detector_view(view, node: DetectorNode) -> DiagnosticsDetectorView:
    return DiagnosticsDetectorView(
        label=detector_label(view) or node.detector_type,
        detector_type=node.detector_type,
        threshold_label=format_score(view.minimum_score),
        current_label=format_score(view.latest_score),
        max_label=format_score(view.max_score),
        references=tuple(
            ReferenceImageView(reference.label, reference.image)
            for reference in node.reference_images
        ),
    )


def _condition_view(
    node: ConditionNode,
    index: ObservationIndex,
) -> DiagnosticsConditionView:
    view = view_for(node, index)
    detector = None if node.detector is None else _detector_view(view, node.detector)
    return DiagnosticsConditionView(
        label=_condition_label(view),
        active=view.active,
        detector=detector,
        children=tuple(_condition_view(child, index) for child in node.children),
    )


def _rule_view(
    rule: RuleNode | RuleSequenceNode, index: ObservationIndex
) -> DiagnosticsRuleView:
    if isinstance(rule, RuleSequenceNode):
        return DiagnosticsRuleView(
            label=f"Rule {rule.rule_index} (sequence)",
            conditions=(),
            steps=tuple(
                DiagnosticsRuleView(
                    label=f"Step {step.rule_index} ({step.action})",
                    conditions=(_condition_view(step.condition, index),),
                    steps=(),
                )
                for step in rule.rules
            ),
        )
    return DiagnosticsRuleView(
        label=f"Rule {rule.rule_index} ({rule.action})",
        conditions=(_condition_view(rule.condition, index),),
        steps=(),
    )


def _single_condition_group(
    kind: str,
    label: str,
    node: ConditionNode,
    index: ObservationIndex,
) -> DiagnosticsGroupView:
    return DiagnosticsGroupView(
        kind=kind,
        label=label,
        conditions=(_condition_view(node, index),),
        rules=(),
    )


def _connection_view(
    scenario: ScenarioNode,
    status: InstanceStatus | None,
) -> DiagnosticsConnectionView:
    if status is None:
        return DiagnosticsConnectionView(
            state=None,
            status_label="—",
            rpc_endpoint=scenario.connection.rpc_endpoint,
            event_endpoint=scenario.connection.event_endpoint,
            error_label=NO_ERROR_LABEL,
            has_error=False,
        )
    has_error = bool(status.error)
    return DiagnosticsConnectionView(
        state=status.state,
        status_label=instance_state_label(status.state),
        rpc_endpoint=scenario.connection.rpc_endpoint,
        event_endpoint=scenario.connection.event_endpoint,
        error_label=status.error if status.error else NO_ERROR_LABEL,
        has_error=has_error,
    )


def build_scenario_diagnostics(
    scenario: ScenarioNode,
    index: ObservationIndex,
    *,
    run_info: LiveSplitRunInfo | None,
    status: InstanceStatus | None,
) -> ScenarioDiagnosticsView:
    """Build one scenario's Diagnostics from its tree node and observations."""

    groups: list[DiagnosticsGroupView] = [
        _single_condition_group(
            START_KIND, START_GROUP_LABEL, scenario.start_condition, index
        )
    ]
    if scenario.reset_condition is not None:
        groups.append(
            _single_condition_group(
                RESET_KIND, RESET_GROUP_LABEL, scenario.reset_condition, index
            )
        )
    if scenario.incomplete_condition is not None:
        groups.append(
            _single_condition_group(
                INCOMPLETE_KIND,
                INCOMPLETE_GROUP_LABEL,
                scenario.incomplete_condition,
                index,
            )
        )
    for split in scenario.splits:
        groups.append(
            DiagnosticsGroupView(
                kind=SPLIT_KIND,
                label=split_label(split.split_index, run_info),
                conditions=(),
                rules=tuple(_rule_view(rule, index) for rule in split.rules),
            )
        )
    return ScenarioDiagnosticsView(
        scenario_index=scenario.scenario_index,
        label=f"Scenario {scenario.scenario_index}",
        connection=_connection_view(scenario, status),
        groups=tuple(groups),
    )


def diagnostics_view(
    tree: DetectorTreeSnapshot | None,
    observations: tuple[ConditionObservation, ...],
    run_infos: tuple[InstanceRunSnapshot, ...],
    statuses: tuple[InstanceStatus, ...],
) -> DiagnosticsView:
    """Build the full Diagnostics model from one monitor snapshot.

    Returns an empty view with ``tree_key`` ``None`` before a session publishes
    a tree. The observations are joined to the tree by identity once here.
    """

    if tree is None:
        return DiagnosticsView(tree_key=None, scenarios=())
    index = ObservationIndex.build(observations)
    runs = {snapshot.scenario_index: snapshot.run_info for snapshot in run_infos}
    status_by_index = {status.scenario_index: status for status in statuses}
    return DiagnosticsView(
        tree_key=tree,
        scenarios=tuple(
            build_scenario_diagnostics(
                scenario,
                index,
                run_info=runs.get(scenario.scenario_index),
                status=status_by_index.get(scenario.scenario_index),
            )
            for scenario in tree.scenarios
        ),
    )
