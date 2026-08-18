"""Rule: a timed execution instance that owns per-node logic instances."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from divergencesplitter.models import FrameContext


class RuleFrameEvaluation:
    """Per-frame view over a rule's node logic during staging.

    ``evaluate`` runs the caller-provided callable against the working copy of
    the node's logic and returns the fired boolean. The first evaluation for a
    node runs the callable once; every later call for the same node returns the
    cached boolean and does not run it again, so a shared node evaluates at most
    once per frame.
    """

    def __init__(self, instances: dict[str, Any]) -> None:
        self._instances = instances
        self._results: dict[str, bool] = {}

    def evaluate(self, node_id: str, step: Callable[[Any], bool]) -> bool:
        if node_id not in self._instances:
            raise ValueError(f"unknown node_id: {node_id!r}")
        if node_id in self._results:
            return self._results[node_id]
        result = step(self._instances[node_id])
        if type(result) is not bool:
            raise TypeError(
                f"step for node_id {node_id!r} must return a strict bool, got {result!r}"
            )
        self._results[node_id] = result
        return result


@dataclass(frozen=True)
class RuleStage:
    """Opaque staged result of a single :meth:`Rule.stage` call.

    All data validation happens while staging. ``_next_instances`` holds the
    working copies of the node logic; :meth:`Rule.commit` adopts them as the
    rule's state.
    """

    _owner: Rule
    _generation: int
    _next_instances: dict[str, Any]
    result: bool


class Rule:
    """A timed execution instance that owns the logic instances of its nodes.

    Holds one logic instance per declared node id and evaluates a Python
    ``evaluator`` against a ``FrameContext``. The evaluator organizes
    ``Detector`` -> ``ScoreThreshold`` -> boolean logic and advances stateful
    nodes through :meth:`RuleFrameEvaluation.evaluate`, keyed by the declared
    node id. Logic instances are created by the node factories when the rule is
    created, carried across frames, and discarded with the rule. A regenerated
    rule starts from fresh logic.

    A single-frame evaluation is read -> evaluate -> stage -> commit. The
    evaluator runs against deep copies of the owned logic, so the rule's logic
    is not changed until :meth:`commit`; an exception or a non-boolean result
    during staging leaves the rule state unchanged.
    """

    def __init__(
        self,
        logic_factories: Mapping[str, Callable[[], Any]],
        evaluator: Callable[[FrameContext, RuleFrameEvaluation], bool],
    ) -> None:
        self._instances: dict[str, Any] = {}
        for node_id, factory in logic_factories.items():
            if not isinstance(node_id, str) or not node_id:
                raise ValueError(f"node_id must be a non-empty str: {node_id!r}")
            self._instances[node_id] = factory()
        self._evaluator = evaluator
        self._generation = 0

    def stage(self, context: FrameContext) -> RuleStage:
        self._generation += 1
        generation = self._generation
        working = {
            node_id: deepcopy(instance) for node_id, instance in self._instances.items()
        }
        evaluation = RuleFrameEvaluation(working)
        result = self._evaluator(context, evaluation)
        if type(result) is not bool:
            raise TypeError(f"evaluator must return a strict bool, got {result!r}")
        return RuleStage(
            _owner=self,
            _generation=generation,
            _next_instances=working,
            result=result,
        )

    def commit(self, stage: RuleStage) -> None:
        if stage._owner is not self:
            raise ValueError("stage does not belong to this rule")
        if stage._generation != self._generation:
            raise ValueError("stale stage")
        self._instances = dict(stage._next_instances)
