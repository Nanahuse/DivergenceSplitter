"""Rule: a timed execution instance that owns per-node logic instances."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from divergencesplitter.models import FrameContext


class RuleFrameEvaluation:
    """Per-frame two-phase view over a rule's node logic during staging.

    A frame is evaluated in two phases. In the *transition phase*, the
    ``transitioner`` advances every stateful node through
    :meth:`transition`, which runs the caller-provided ``step`` against the
    working copy of the node's logic exactly once and caches the returned
    boolean. Once every declared node has been transitioned, the phase is
    sealed. In the *result phase*, the ``evaluator`` reads the cached booleans
    through :meth:`result` and composes them (with pure predicates) into the
    frame's fired boolean.

    Each declared node is transitioned exactly once: a second transition of
    the same node, or a re-entrant transition while that node's ``step`` is
    still running, fails fast with :class:`RuntimeError` rather than returning
    a cached or recursive result. Shared references to a node's boolean must
    be read through :meth:`result` in the result phase.

    The seal keeps stateful transitions out of the result phase: short-circuit
    composition in the result phase can skip cached-result reads and pure
    predicates, but it cannot skip the transition of a stateful node.
    """

    def __init__(self, instances: dict[str, Any]) -> None:
        self._instances = instances
        self._results: dict[str, bool] = {}
        self._in_progress: set[str] = set()
        self._sealed = False

    def transition(self, node_id: str, step: Callable[[Any], bool]) -> bool:
        if self._sealed:
            raise RuntimeError("transition phase is already sealed")
        if node_id not in self._instances:
            raise ValueError(f"unknown node_id: {node_id!r}")
        if node_id in self._in_progress:
            raise RuntimeError(f"re-entrant transition of node_id {node_id!r}")
        if node_id in self._results:
            raise RuntimeError(f"node_id {node_id!r} already transitioned")
        self._in_progress.add(node_id)
        try:
            result = step(self._instances[node_id])
        finally:
            self._in_progress.discard(node_id)
        if type(result) is not bool:
            raise TypeError(
                f"step for node_id {node_id!r} must return a strict bool, got {result!r}"
            )
        self._results[node_id] = result
        return result

    def result(self, node_id: str) -> bool:
        if not self._sealed:
            raise RuntimeError("transition phase is not sealed")
        if node_id not in self._instances:
            raise ValueError(f"unknown node_id: {node_id!r}")
        return self._results[node_id]

    def _seal(self) -> None:
        missing = [
            node_id for node_id in self._instances if node_id not in self._results
        ]
        if missing:
            raise RuntimeError(f"nodes not transitioned: {missing!r}")
        self._sealed = True


@dataclass(frozen=True)
class RuleStage:
    """Opaque staged result of a single :meth:`Rule.stage` call.

    All data validation happens while staging. The stage carries only opaque
    ownership tokens (``_owner`` and ``_generation``) plus the computed
    ``result`` boolean. The working copies of the node logic are held inside
    the owning :class:`Rule` as its pending stage and are adopted on
    :meth:`Rule.commit`; callers cannot reach or mutate the rule's logic
    through a stage object.
    """

    _owner: Rule
    _generation: int
    result: bool


class Rule:
    """A timed execution instance that owns the logic instances of its nodes.

    Holds one logic instance per declared node id and evaluates a Python
    ``transitioner`` then an ``evaluator`` against a ``FrameContext``. The
    transitioner transitions every stateful node through
    :meth:`RuleFrameEvaluation.transition`, keyed by the declared node id,
    computing each node's input with a ``Detector`` -> ``ScoreThreshold`` ->
    logic step chain before the transition. The evaluator composes the cached
    booleans (via :meth:`RuleFrameEvaluation.result`) with pure predicates
    into the frame's fired boolean. Logic instances are created by the node
    factories when the rule is created, carried across frames, and discarded
    with the rule. A regenerated rule starts from fresh logic.

    A single-frame evaluation is read -> transition -> seal -> result ->
    stage -> commit. The transitioner and evaluator run against deep copies of
    the owned logic, so the rule's logic is not changed until :meth:`commit`;
    an exception, a skipped transition, or a non-boolean result during staging
    leaves the rule state unchanged.

    Each successful :meth:`stage` replaces the rule's single pending stage with
    its working copies and returns an opaque :class:`RuleStage` token;
    :meth:`commit` adopts that pending stage and clears it. Committing a
    foreign or stale stage, or committing a stage twice, is rejected. Rules
    can each be staged ahead of a later commit, but each rule keeps at most one
    pending stage.
    """

    def __init__(
        self,
        logic_factories: Mapping[str, Callable[[], Any]],
        transitioner: Callable[[FrameContext, RuleFrameEvaluation], None],
        evaluator: Callable[[FrameContext, RuleFrameEvaluation], bool],
    ) -> None:
        self._instances: dict[str, Any] = {}
        for node_id, factory in logic_factories.items():
            if not isinstance(node_id, str) or not node_id:
                raise ValueError(f"node_id must be a non-empty str: {node_id!r}")
            self._instances[node_id] = factory()
        self._transitioner = transitioner
        self._evaluator = evaluator
        self._generation = 0
        self._pending: dict[str, Any] | None = None

    def stage(self, context: FrameContext) -> RuleStage:
        self._generation += 1
        generation = self._generation
        self._pending = None
        working = {
            node_id: deepcopy(instance) for node_id, instance in self._instances.items()
        }
        evaluation = RuleFrameEvaluation(working)
        self._transitioner(context, evaluation)
        evaluation._seal()
        result = self._evaluator(context, evaluation)
        if type(result) is not bool:
            raise TypeError(f"evaluator must return a strict bool, got {result!r}")
        self._pending = working
        return RuleStage(
            _owner=self,
            _generation=generation,
            result=result,
        )

    def commit(self, stage: RuleStage) -> None:
        if stage._owner is not self:
            raise ValueError("stage does not belong to this rule")
        if stage._generation != self._generation:
            raise ValueError("stale stage")
        if self._pending is None:
            raise ValueError("stage already committed")
        self._instances = self._pending
        self._pending = None
