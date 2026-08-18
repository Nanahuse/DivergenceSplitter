"""Scenario rule: a timed execution instance that evaluates detector input."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from divergencesplitter.models import (
    ActionCandidate,
    FrameContext,
    LiveSplitSnapshot,
    TimerOperation,
)


class RuleFrameEvaluation:
    """Per-frame view over a rule's node states during staging.

    ``transition`` runs the caller-provided step against the current state of a
    node and returns the fired boolean. The first call for a node runs the step
    once; every later call for the same node returns the cached boolean and does
    not run the step again, so a shared node transitions at most once per frame.
    """

    def __init__(self, states: dict[str, Any]) -> None:
        self._states = states
        self._results: dict[str, bool] = {}

    def transition(self, node_id: str, step: Callable[[Any], tuple[bool, Any]]) -> bool:
        if node_id not in self._states:
            raise ValueError(f"unknown node_id: {node_id!r}")
        if node_id in self._results:
            return self._results[node_id]
        fired, next_state = step(self._states[node_id])
        if type(fired) is not bool:
            raise TypeError(
                f"step for node_id {node_id!r} must return a strict bool, got {fired!r}"
            )
        self._states[node_id] = next_state
        self._results[node_id] = fired
        return fired


@dataclass(frozen=True)
class RuleStage:
    """Opaque staged result of a single :meth:`Rule.stage` call.

    All data validation happens while staging. ``_next_state`` is exposed as a
    read-only mapping so external code cannot mutate a staged transaction;
    :meth:`Rule.commit` applies it as a single replacement.
    """

    _owner: Rule
    _generation: int
    _next_state: Mapping[str, Any]
    candidate: ActionCandidate | None


class Rule:
    """A timed execution instance owned by a scenario.

    Holds the logic state per declared node and evaluates a Python ``evaluator``
    against a ``FrameContext``. When the evaluator returns ``True`` the rule
    produces an ``ActionCandidate`` carrying the snapshot it fired on.
    """

    def __init__(
        self,
        scenario_id: str,
        target_id: str,
        rule_id: str,
        operation: TimerOperation,
        priority: int,
        initial_states: Mapping[str, Callable[[], Any]],
        evaluator: Callable[[FrameContext, RuleFrameEvaluation], bool],
    ) -> None:
        if not scenario_id:
            raise ValueError("scenario_id must not be empty")
        if not target_id:
            raise ValueError("target_id must not be empty")
        if not rule_id:
            raise ValueError("rule_id must not be empty")
        self.scenario_id = scenario_id
        self.target_id = target_id
        self.rule_id = rule_id
        self.operation = operation
        self.priority = priority
        self._state: dict[str, Any] = {}
        for node_id, initializer in initial_states.items():
            if not isinstance(node_id, str) or not node_id:
                raise ValueError(f"node_id must be a non-empty str: {node_id!r}")
            self._state[node_id] = initializer()
        self._evaluator = evaluator
        self._generation = 0

    def stage(self, context: FrameContext, snapshot: LiveSplitSnapshot) -> RuleStage:
        if snapshot.target_id != self.target_id:
            raise ValueError(
                f"snapshot target mismatch: expected {self.target_id!r}, "
                f"got {snapshot.target_id!r}"
            )
        self._generation += 1
        generation = self._generation
        working = dict(self._state)
        evaluation = RuleFrameEvaluation(working)
        fired = self._evaluator(context, evaluation)
        if type(fired) is not bool:
            raise TypeError(
                f"evaluator for rule {self.rule_id!r} must return a strict "
                f"bool, got {fired!r}"
            )
        candidate = None
        if fired:
            candidate = ActionCandidate(
                scenario_id=self.scenario_id,
                target_id=self.target_id,
                operation=self.operation,
                rule_id=self.rule_id,
                priority=self.priority,
                expected_snapshot=snapshot,
            )
        return RuleStage(
            _owner=self,
            _generation=generation,
            _next_state=MappingProxyType(working),
            candidate=candidate,
        )

    def commit(self, stage: RuleStage) -> None:
        if stage._owner is not self:
            raise ValueError("stage does not belong to this rule")
        if stage._generation != self._generation:
            raise ValueError("stale stage")
        self._state = dict(stage._next_state)
