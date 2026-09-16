"""Pure Scenario Overview presentation model for the Monitor.

Builds immutable view values from the monitor snapshot's detector tree,
condition observations, run info, instance statuses, and evaluation metrics.
Nothing here imports a GUI framework; the Flet Scenario Overview control only
renders these values. The model reuses ``presentation`` joining and formatting
helpers so the Overview never re-implements condition resolution.

The model reports only *currently evaluated* material: a condition appears when
``ConditionObservation.active`` is true or when it has an active descendant, so
a condition that merely holds a stale TRUE/FALSE result is never shown. A single
active chain is compacted with ``→``; a node with several active children keeps
its branches nested so no branch is dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from divergencesplitter_runtime.instance_runtime import (
    InstanceRuntimeState,
    InstanceStatus,
)
from divergencesplitter_runtime.livesplit.models import LiveSplitRunInfo
from divergencesplitter_runtime.metrics import (
    InstanceEvaluationMetrics,
    RuntimeMetricsSnapshot,
)
from divergencesplitter_runtime.observability import (
    ConditionNode,
    ConditionObservation,
    DetectorTreeSnapshot,
    InstanceRunSnapshot,
    RuleNode,
    RuleSequenceNode,
    ScenarioNode,
)

from divergencesplitter_ui.presentation import (
    ObservationIndex,
    condition_progress_label,
    format_latency_ms,
    instance_state_label,
    split_label,
    view_for,
)

START_GROUP_LABEL = "Start"
RESET_GROUP_LABEL = "Reset"
INCOMPLETE_GROUP_LABEL = "Incomplete"
UNMEASURED_LATENCY = "—"
STATUS_UNKNOWN_LABEL = "—"


class EvaluationKind(Enum):
    """The scenario position an evaluation group represents."""

    START = auto()
    RESET = auto()
    INCOMPLETE = auto()
    SPLIT = auto()


@dataclass(frozen=True)
class ConditionEvaluationView:
    """One active condition line, possibly a compacted single chain.

    ``label`` is the condition type or a ``A → B`` chain. ``detail`` carries the
    progress or detector score text, and ``children`` holds the branches that
    must stay nested.
    """

    label: str
    detail: str = ""
    children: tuple[ConditionEvaluationView, ...] = ()


@dataclass(frozen=True)
class RuleEvaluationView:
    """One rule position and its active condition(s).

    ``label`` is ``None`` for the single-condition Start/Reset/Incomplete
    groups, ``Rule N`` for a plain rule, and ``Rule N / Step M`` for a
    RuleSequence step.
    """

    label: str | None
    conditions: tuple[ConditionEvaluationView, ...]


@dataclass(frozen=True)
class EvaluationGroupView:
    """One active evaluation position: Start, Reset, Incomplete, or a Split."""

    kind: EvaluationKind
    label: str
    rules: tuple[RuleEvaluationView, ...]


@dataclass(frozen=True)
class EvaluationPerformanceView:
    """One scenario's evaluation latency formatted for the Overview footer."""

    average_label: str
    max_label: str


@dataclass(frozen=True)
class ScenarioStatusView:
    """One scenario's connection status with its state for color mapping."""

    state: InstanceRuntimeState | None
    label: str


@dataclass(frozen=True)
class ScenarioCardView:
    """Everything the Overview shows for one scenario."""

    scenario_index: int
    status: ScenarioStatusView
    evaluation_groups: tuple[EvaluationGroupView, ...]
    evaluation: EvaluationPerformanceView


@dataclass(frozen=True)
class ScenarioOverviewView:
    """The complete Overview model for every scenario."""

    scenarios: tuple[ScenarioCardView, ...]


def _join_detail(outer: str, inner: str) -> str:
    parts = [part for part in (outer, inner) if part]
    return "   ".join(parts)


def _condition_view(
    node: ConditionNode,
    index: ObservationIndex,
) -> ConditionEvaluationView | None:
    view = view_for(node, index)
    children = tuple(
        child
        for child in (_condition_view(item, index) for item in node.children)
        if child is not None
    )
    if not view.active and not children:
        return None
    detail = condition_progress_label(view)
    if len(children) == 1:
        child = children[0]
        return ConditionEvaluationView(
            label=f"{view.condition_type} → {child.label}",
            detail=_join_detail(detail, child.detail),
            children=child.children,
        )
    return ConditionEvaluationView(
        label=view.condition_type,
        detail=detail,
        children=children,
    )


def _rule_views(
    rule: RuleNode | RuleSequenceNode,
    index: ObservationIndex,
) -> tuple[RuleEvaluationView, ...]:
    if isinstance(rule, RuleSequenceNode):
        step_views = []
        for step in rule.rules:
            condition = _condition_view(step.condition, index)
            if condition is None:
                continue
            step_views.append(
                RuleEvaluationView(
                    label=f"Rule {rule.rule_index} / Step {step.rule_index}",
                    conditions=(condition,),
                )
            )
        return tuple(step_views)
    condition = _condition_view(rule.condition, index)
    if condition is None:
        return ()
    return (
        RuleEvaluationView(
            label=f"Rule {rule.rule_index}",
            conditions=(condition,),
        ),
    )


def _single_condition_group(
    kind: EvaluationKind,
    label: str,
    node: ConditionNode,
    index: ObservationIndex,
) -> EvaluationGroupView | None:
    condition = _condition_view(node, index)
    if condition is None:
        return None
    return EvaluationGroupView(
        kind=kind,
        label=label,
        rules=(RuleEvaluationView(label=None, conditions=(condition,)),),
    )


def _evaluation_performance(
    metrics: InstanceEvaluationMetrics | None,
) -> EvaluationPerformanceView:
    if metrics is None:
        return EvaluationPerformanceView(
            average_label=UNMEASURED_LATENCY,
            max_label=UNMEASURED_LATENCY,
        )
    return EvaluationPerformanceView(
        average_label=format_latency_ms(metrics.average_latency_ns),
        max_label=format_latency_ms(metrics.max_latency_ns),
    )


def build_scenario_card(
    scenario: ScenarioNode,
    index: ObservationIndex,
    *,
    run_info: LiveSplitRunInfo | None,
    status: InstanceStatus | None,
    metrics: InstanceEvaluationMetrics | None,
) -> ScenarioCardView:
    """Build one scenario card from its tree node and current observations."""

    groups: list[EvaluationGroupView] = []
    for split in scenario.splits:
        rule_views: list[RuleEvaluationView] = []
        for rule in split.rules:
            rule_views.extend(_rule_views(rule, index))
        if rule_views:
            groups.append(
                EvaluationGroupView(
                    kind=EvaluationKind.SPLIT,
                    label=split_label(split.split_index, run_info),
                    rules=tuple(rule_views),
                )
            )
    for kind, label, condition_node in (
        (EvaluationKind.START, START_GROUP_LABEL, scenario.start_condition),
        (EvaluationKind.RESET, RESET_GROUP_LABEL, scenario.reset_condition),
        (
            EvaluationKind.INCOMPLETE,
            INCOMPLETE_GROUP_LABEL,
            scenario.incomplete_condition,
        ),
    ):
        if condition_node is None:
            continue
        group = _single_condition_group(kind, label, condition_node, index)
        if group is not None:
            groups.append(group)
    return ScenarioCardView(
        scenario_index=scenario.scenario_index,
        status=ScenarioStatusView(
            state=None if status is None else status.state,
            label=(
                STATUS_UNKNOWN_LABEL
                if status is None
                else instance_state_label(status.state)
            ),
        ),
        evaluation_groups=tuple(groups),
        evaluation=_evaluation_performance(metrics),
    )


def scenario_overview_view(
    tree: DetectorTreeSnapshot | None,
    observations: tuple[ConditionObservation, ...],
    run_infos: tuple[InstanceRunSnapshot, ...],
    statuses: tuple[InstanceStatus, ...],
    metrics: RuntimeMetricsSnapshot | None,
) -> ScenarioOverviewView:
    """Build the complete Overview model from one monitor snapshot.

    The observations are joined to the tree by condition object identity exactly
    once here, so the Overview and any later consumer share one resolution pass.
    An empty ``tree`` yields an empty Overview.
    """

    if tree is None:
        return ScenarioOverviewView(scenarios=())
    index = ObservationIndex.build(observations)
    runs = {snapshot.scenario_index: snapshot.run_info for snapshot in run_infos}
    status_by_index = {status.scenario_index: status for status in statuses}
    metrics_by_index: dict[int, InstanceEvaluationMetrics] = {}
    if metrics is not None:
        metrics_by_index = {
            item.scenario_index: item for item in metrics.instance_evaluations
        }
    return ScenarioOverviewView(
        scenarios=tuple(
            build_scenario_card(
                scenario,
                index,
                run_info=runs.get(scenario.scenario_index),
                status=status_by_index.get(scenario.scenario_index),
                metrics=metrics_by_index.get(scenario.scenario_index),
            )
            for scenario in tree.scenarios
        )
    )
