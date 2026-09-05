"""Transfer-only observability values exposed to desktop UI consumers.

These frozen dataclasses carry data and perform value validation only. They do
not build, update, or format the display; the desktop UI owns presentation.
"""

from __future__ import annotations

from dataclasses import dataclass

from divergencesplitter import (
    Condition,
    ConditionStatus,
    Detected,
    ImageDetector,
    ObservableCondition,
    ReferenceImage,
    Rule,
    Scenario,
)


@dataclass(frozen=True)
class DetectorNode:
    """One detector occurrence in the display tree."""

    detector: ImageDetector
    detector_type: str
    minimum_score: float | None
    reference_images: tuple[ReferenceImage, ...]


@dataclass(frozen=True)
class ConditionNode:
    """A condition and its nested children in the display tree."""

    condition: Condition
    condition_type: str
    children: tuple[ConditionNode, ...] = ()
    detector: DetectorNode | None = None


@dataclass(frozen=True)
class RuleNode:
    """A rule position with its condition subtree."""

    rule_index: int
    action: str
    condition: ConditionNode


@dataclass(frozen=True)
class SplitNode:
    """A split position with its rules in declaration order."""

    split_index: int
    rules: tuple[RuleNode, ...]


@dataclass(frozen=True)
class ScenarioNode:
    """The display structure of one scenario."""

    scenario_index: int
    reset_conditions: tuple[ConditionNode, ...]
    splits: tuple[SplitNode, ...]


@dataclass(frozen=True)
class DetectorTreeSnapshot:
    """Immutable display tree for all scenarios."""

    scenarios: tuple[ScenarioNode, ...]


@dataclass(frozen=True)
class ConditionObservation:
    """One condition's latest evaluation outcome and detector scores.

    ``latest_score`` and ``max_score`` are ``None`` for conditions without a
    detector and for a detector that has not run since start or reset. The
    observation carries the source ``condition`` so consumers can join it to the
    display tree by identity without reading the condition's private state.
    """

    condition: Condition
    status: ConditionStatus | None
    latest_score: float | None
    max_score: float | None


def build_detector_tree(scenarios: tuple[Scenario, ...]) -> DetectorTreeSnapshot:
    """Build an immutable display tree from pre-constructed scenarios."""

    return DetectorTreeSnapshot(
        scenarios=tuple(
            _scenario_node(scenario_index, scenario)
            for scenario_index, scenario in enumerate(scenarios)
        )
    )


def _scenario_node(scenario_index: int, scenario: Scenario) -> ScenarioNode:
    return ScenarioNode(
        scenario_index=scenario_index,
        reset_conditions=tuple(
            _condition_node(item) for item in scenario.reset_conditions
        ),
        splits=tuple(
            _split_node(index, rules) for index, rules in enumerate(scenario.splits)
        ),
    )


def _split_node(index: int, rules: tuple[Rule, ...] | None) -> SplitNode:
    if rules is None:
        return SplitNode(split_index=index, rules=())
    return SplitNode(
        split_index=index,
        rules=tuple(
            _rule_node(rule_index, rule) for rule_index, rule in enumerate(rules)
        ),
    )


def _rule_node(rule_index: int, rule: Rule) -> RuleNode:
    return RuleNode(
        rule_index=rule_index,
        action=rule.action.operation,
        condition=_condition_node(rule.condition),
    )


def _condition_node(condition: Condition) -> ConditionNode:
    if isinstance(condition, Detected):
        detector = condition.detector
        return ConditionNode(
            condition=condition,
            condition_type=type(condition).__name__,
            detector=DetectorNode(
                detector=detector,
                detector_type=type(detector).__name__,
                minimum_score=condition.minimum_score,
                reference_images=detector.reference_images,
            ),
        )
    return ConditionNode(
        condition=condition,
        condition_type=type(condition).__name__,
        children=tuple(_condition_node(item) for item in condition.children),
    )


def _collect_condition_observations(
    scenarios: tuple[Scenario, ...],
) -> tuple[ConditionObservation, ...]:
    """Read the latest evaluation outcome of every condition in ``scenarios``.

    Each condition instance is reported once even when it is reused in several
    positions, preserving the shared-state meaning of a reused instance. Values
    are copied out so the result does not expose mutable condition state.
    """

    seen: set[int] = set()
    observations: list[ConditionObservation] = []

    def visit(condition: Condition) -> None:
        identity = id(condition)
        if identity in seen:
            return
        seen.add(identity)
        latest_score: float | None = None
        max_score: float | None = None
        if isinstance(condition, Detected):
            if condition.status in (ConditionStatus.TRUE, ConditionStatus.FALSE):
                latest_score = condition.latest_score
            max_score = condition.max_score
        status = (
            condition.status if isinstance(condition, ObservableCondition) else None
        )
        observations.append(
            ConditionObservation(
                condition=condition,
                status=status,
                latest_score=latest_score,
                max_score=max_score,
            )
        )
        for child in condition.children:
            visit(child)

    for scenario in scenarios:
        for condition in scenario.reset_conditions:
            visit(condition)
        for rules in scenario.splits:
            if rules is None:
                continue
            for rule in rules:
                visit(rule.condition)

    return tuple(observations)
