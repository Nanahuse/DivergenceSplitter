"""Transfer-only observability values exposed to desktop UI consumers.

These frozen dataclasses carry data and perform value validation only. They do
not build, update, or format the display; the desktop UI owns presentation.
"""

from __future__ import annotations

from dataclasses import dataclass

from divergencesplitter import (
    Condition,
    Detected,
    ImageDetector,
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
class DetectorScore:
    """One detector's latest unevaluated score."""

    detector: ImageDetector
    score: float


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
            condition_type=type(condition).__name__,
            detector=DetectorNode(
                detector=detector,
                detector_type=type(detector).__name__,
                minimum_score=condition.minimum_score,
                reference_images=detector.reference_images,
            ),
        )
    return ConditionNode(
        condition_type=type(condition).__name__,
        children=tuple(_condition_node(item) for item in condition.children),
    )
