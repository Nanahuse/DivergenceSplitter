"""Scenario orchestration: rule lifecycle and per-frame processing."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from divergencesplitter.models import ActionCandidate, FrameContext, LiveSplitSnapshot
from divergencesplitter.rule import Rule, RuleStage

RuleFactory = Callable[[], Rule]
Selector = Callable[[LiveSplitSnapshot], Mapping[str, RuleFactory]]


@dataclass(frozen=True)
class ScenarioSyncStage:
    """Opaque staged rule-set replacement from a single sync pass.

    All validation happens while staging. ``_next_rules`` is exposed as a
    read-only mapping so external code cannot mutate a staged transaction;
    :meth:`Scenario.commit_sync` applies it as a single replacement.
    """

    _owner: Scenario
    _generation: int
    _next_rules: Mapping[str, Rule]


class Scenario:
    """Owns the currently existing rule instances for one target.

    The selector derives the required rule-id-to-factory mapping from the latest
    snapshot. Sync stages a full replacement, reusing existing rules by id and
    generating only new ones (or all, when forced after a freshness gap).
    """

    def __init__(
        self,
        scenario_id: str,
        target_id: str,
        selector: Selector,
    ) -> None:
        if not scenario_id:
            raise ValueError("scenario_id must not be empty")
        if not target_id:
            raise ValueError("target_id must not be empty")
        self.scenario_id = scenario_id
        self.target_id = target_id
        self._selector = selector
        self._rules: dict[str, Rule] = {}
        self._generation = 0
        self._resync_required = False

    @property
    def rules(self) -> Mapping[str, Rule]:
        """Read-only view of the currently existing rule instances."""
        return MappingProxyType(self._rules)

    @property
    def resync_required(self) -> bool:
        """True while a snapshot freshness gap is awaiting resynchronisation."""
        return self._resync_required

    def sync(
        self, snapshot: LiveSplitSnapshot, *, force: bool = False
    ) -> ScenarioSyncStage:
        if snapshot.target_id != self.target_id:
            raise ValueError(
                f"snapshot target mismatch: expected {self.target_id!r}, "
                f"got {snapshot.target_id!r}"
            )
        required = self._selector(snapshot)
        new_rules: dict[str, Rule] = {}
        for rule_id, factory in required.items():
            if not isinstance(rule_id, str) or not rule_id:
                raise ValueError(f"rule_id must be a non-empty str: {rule_id!r}")
            if not force and rule_id in self._rules:
                new_rules[rule_id] = self._rules[rule_id]
                continue
            rule = factory()
            if rule.rule_id != rule_id:
                raise ValueError(
                    f"factory produced rule_id {rule.rule_id!r}, expected {rule_id!r}"
                )
            if rule.scenario_id != self.scenario_id:
                raise ValueError(
                    f"rule scenario mismatch: expected {self.scenario_id!r}, "
                    f"got {rule.scenario_id!r}"
                )
            if rule.target_id != self.target_id:
                raise ValueError(
                    f"rule target mismatch: expected {self.target_id!r}, "
                    f"got {rule.target_id!r}"
                )
            new_rules[rule_id] = rule
        self._generation += 1
        return ScenarioSyncStage(
            _owner=self,
            _generation=self._generation,
            _next_rules=MappingProxyType(new_rules),
        )

    def commit_sync(self, stage: ScenarioSyncStage) -> None:
        if stage._owner is not self:
            raise ValueError("sync stage does not belong to this scenario")
        if stage._generation != self._generation:
            raise ValueError("stale sync stage")
        self._rules = dict(stage._next_rules)


def process_scenarios(
    scenarios: Sequence[Scenario],
    snapshots_by_target: Mapping[str, LiveSplitSnapshot],
    context: FrameContext,
) -> tuple[ActionCandidate, ...]:
    """Process one frame across scenarios.

    Requires every scenario_id and target_id to be unique across the
    scenarios; a duplicate raises ``ValueError`` before any progress is made.
    Then validates every target snapshot first. When any snapshot is not fresh
    the whole cycle makes no progress and returns an empty tuple. Otherwise
    rule sets are synced (staged then committed) and all existing rules are
    staged, then committed only if every stage succeeded.
    """

    ordered = sorted(scenarios, key=lambda scenario: scenario.scenario_id)

    seen_scenario_ids: set[str] = set()
    seen_target_ids: set[str] = set()
    for scenario in ordered:
        if scenario.scenario_id in seen_scenario_ids:
            raise ValueError(f"duplicate scenario_id: {scenario.scenario_id!r}")
        seen_scenario_ids.add(scenario.scenario_id)
        if scenario.target_id in seen_target_ids:
            raise ValueError(f"duplicate target_id: {scenario.target_id!r}")
        seen_target_ids.add(scenario.target_id)

    stale = False
    for scenario in ordered:
        snapshot = snapshots_by_target.get(scenario.target_id)
        if snapshot is None:
            raise KeyError(f"missing snapshot for target_id: {scenario.target_id!r}")
        if snapshot.target_id != scenario.target_id:
            raise ValueError(
                f"snapshot target mismatch: expected {scenario.target_id!r}, "
                f"got {snapshot.target_id!r}"
            )
        if not snapshot.is_fresh:
            scenario._resync_required = True
            stale = True

    if stale:
        return ()

    sync_stages: list[tuple[Scenario, ScenarioSyncStage]] = []
    for scenario in ordered:
        snapshot = snapshots_by_target[scenario.target_id]
        sync_stages.append(
            (scenario, scenario.sync(snapshot, force=scenario._resync_required))
        )

    for scenario, stage in sync_stages:
        scenario.commit_sync(stage)
        scenario._resync_required = False

    rule_stages: list[tuple[Rule, RuleStage]] = []
    for scenario in ordered:
        snapshot = snapshots_by_target[scenario.target_id]
        for rule in sorted(scenario.rules.values(), key=lambda rule: rule.rule_id):
            rule_stages.append((rule, rule.stage(context, snapshot)))

    candidates: list[ActionCandidate] = []
    for rule, stage in rule_stages:
        rule.commit(stage)
        if stage.candidate is not None:
            candidates.append(stage.candidate)

    return tuple(candidates)
