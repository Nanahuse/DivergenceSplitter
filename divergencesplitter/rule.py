from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from divergencesplitter.models import FrameContext


class RuleFrameEvaluation:
    """Transitions every declared node exactly once against staged copies."""

    def __init__(self, instances: dict[str, Any]) -> None:
        self._instances = instances
        self._results: dict[str, bool] = {}
        self._in_progress: set[str] = set()

    def transition(self, node_id: str, step: Callable[[Any], bool]) -> bool:
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
        if node_id not in self._instances:
            raise ValueError(f"unknown node_id: {node_id!r}")
        if node_id not in self._results:
            raise RuntimeError(f"node_id {node_id!r} not yet transitioned")
        return self._results[node_id]

    def _verify_complete(self) -> None:
        missing = [
            node_id for node_id in self._instances if node_id not in self._results
        ]
        if missing:
            raise RuntimeError(f"nodes not transitioned: {missing!r}")


@dataclass(frozen=True)
class RuleStage:
    """Opaque result of one staged evaluation."""

    _owner: Rule
    _generation: int
    result: bool


class Rule:
    """Owns per-node logic and commits state only after successful staging."""

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
        self._pending: dict[str, Any] | None = None

    def stage(self, context: FrameContext) -> RuleStage:
        self._generation += 1
        generation = self._generation
        self._pending = None
        working = {
            node_id: deepcopy(instance) for node_id, instance in self._instances.items()
        }
        evaluation = RuleFrameEvaluation(working)
        result = self._evaluator(context, evaluation)
        if type(result) is not bool:
            raise TypeError(f"evaluator must return a strict bool, got {result!r}")
        evaluation._verify_complete()
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
