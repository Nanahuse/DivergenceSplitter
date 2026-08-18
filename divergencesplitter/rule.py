"""Rule: a timed execution instance that owns per-node logic state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from divergencesplitter.models import FrameContext


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
    result: bool


class Rule:
    """A timed execution instance that owns the logic state of its nodes.

    Holds the logic state per declared node id and evaluates a Python
    ``evaluator`` against a ``FrameContext``. The evaluator organizes
    ``Detector`` -> ``ScoreThreshold`` -> boolean logic and advances stateful
    nodes through :meth:`RuleFrameEvaluation.transition`, keyed by the declared
    node id. Node state is initialized when the rule is created, carried across
    frames, and discarded with the rule. A regenerated rule starts from fresh
    state.

    A single-frame evaluation is read -> transition -> stage -> commit. The
    staged state is not applied until :meth:`commit`; an exception or a
    non-boolean result during staging leaves the rule state unchanged.
    """

    def __init__(
        self,
        initial_states: Mapping[str, Callable[[], Any]],
        evaluator: Callable[[FrameContext, RuleFrameEvaluation], bool],
    ) -> None:
        self._state: dict[str, Any] = {}
        for node_id, initializer in initial_states.items():
            if not isinstance(node_id, str) or not node_id:
                raise ValueError(f"node_id must be a non-empty str: {node_id!r}")
            self._state[node_id] = initializer()
        self._evaluator = evaluator
        self._generation = 0

    def stage(self, context: FrameContext) -> RuleStage:
        self._generation += 1
        generation = self._generation
        working = dict(self._state)
        evaluation = RuleFrameEvaluation(working)
        result = self._evaluator(context, evaluation)
        if type(result) is not bool:
            raise TypeError(f"evaluator must return a strict bool, got {result!r}")
        return RuleStage(
            _owner=self,
            _generation=generation,
            _next_state=MappingProxyType(working),
            result=result,
        )

    def commit(self, stage: RuleStage) -> None:
        if stage._owner is not self:
            raise ValueError("stage does not belong to this rule")
        if stage._generation != self._generation:
            raise ValueError("stale stage")
        self._state = dict(stage._next_state)
