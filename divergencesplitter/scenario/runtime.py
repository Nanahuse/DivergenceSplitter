import logging
from dataclasses import dataclass

from divergencesplitter.frame.models import FrameContext
from divergencesplitter.livesplit.models import (
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    TimerPhase,
)
from divergencesplitter.rule import Action, Rule
from divergencesplitter.scenario.definition import RuleDefinition, ScenarioDefinition

SPLIT_TRANSITION_TIMEOUT_NANOSECONDS = 1_000_000_000


@dataclass(frozen=True)
class _RuntimeRule:
    definition: RuleDefinition
    rule: Rule


class ScenarioRuntime:
    def __init__(
        self,
        definition: ScenarioDefinition,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._definition = definition
        self._logger = logger or logging.getLogger(__name__)
        self._rules = self._build_rules(definition)
        self._snapshot: LiveSplitSnapshot | None = None
        self._awaiting_resync = False
        self._configuration_valid = True
        self._action_started_at: int | None = None

    @staticmethod
    def _build_rules(
        definition: ScenarioDefinition,
    ) -> dict[int, tuple[_RuntimeRule, ...]]:
        result: dict[int, tuple[_RuntimeRule, ...]] = {}
        condition_ids: set[int] = set()
        for split_index, rule_definitions in definition.rules.items():
            runtime_rules: list[_RuntimeRule] = []
            for rule_definition in rule_definitions:
                action = rule_definition.action
                if action.scenario_id != definition.scenario_id:
                    raise ValueError(
                        "Action scenario_id does not match ScenarioDefinition"
                    )
                if action.target_id != definition.target_id:
                    raise ValueError(
                        "Action target_id does not match ScenarioDefinition"
                    )
                condition = rule_definition.condition_factory()
                if id(condition) in condition_ids:
                    raise ValueError("condition_factory must return a fresh Condition")
                condition_ids.add(id(condition))
                runtime_rules.append(
                    _RuntimeRule(
                        definition=rule_definition,
                        rule=Rule(condition=condition, action=action),
                    )
                )
            result[split_index] = tuple(runtime_rules)
        return result

    def apply_livesplit_update(self, update: LiveSplitUpdate) -> None:
        snapshot = update.snapshot
        if snapshot.target_id != self._definition.target_id:
            self._log(
                logging.WARNING,
                "scenario_runtime.target_mismatch",
                received_target_id=snapshot.target_id,
            )
            return

        current = self._snapshot
        if current is None:
            if update.kind not in (
                LiveSplitUpdateKind.INITIAL,
                LiveSplitUpdateKind.RESYNC,
            ):
                self._log(logging.WARNING, "scenario_runtime.initial_sync_required")
                return
            self._establish_baseline(snapshot)
            return

        if snapshot.session_id != current.session_id:
            if update.kind is not LiveSplitUpdateKind.RESYNC:
                self._awaiting_resync = True
                self._log(
                    logging.WARNING,
                    "scenario_runtime.session_resync_required",
                    received_session_id=snapshot.session_id,
                )
                return
            self._reset_all_rules()
            self._action_started_at = None
            self._awaiting_resync = False
            self._establish_baseline(snapshot)
            self._log(logging.INFO, "scenario_runtime.session_resynced")
            return

        if snapshot.event_sequence <= current.event_sequence:
            self._log(logging.DEBUG, "scenario_runtime.update_ignored")
            return

        if update.kind is LiveSplitUpdateKind.INITIAL:
            self._log(logging.WARNING, "scenario_runtime.initial_update_ignored")
            return

        if update.kind is LiveSplitUpdateKind.RESYNC:
            self._apply_resync(snapshot, current)
            return

        if self._awaiting_resync:
            self._log(logging.DEBUG, "scenario_runtime.awaiting_resync")
            return

        if snapshot.event_sequence != current.event_sequence + 1:
            self._awaiting_resync = True
            self._log(
                logging.WARNING,
                "scenario_runtime.update_gap",
                received_event_sequence=snapshot.event_sequence,
            )
            return

        if snapshot.state_revision < current.state_revision:
            self._log(logging.WARNING, "scenario_runtime.revision_regressed")
            return

        if update.kind is LiveSplitUpdateKind.PERIODIC and self._state_changed(
            current,
            snapshot,
        ):
            self._awaiting_resync = True
            self._log(logging.WARNING, "scenario_runtime.invalid_periodic_update")
            return

        self._snapshot = snapshot
        self._configuration_valid = self._validate_split_count(snapshot)
        if update.kind is LiveSplitUpdateKind.TRANSITION:
            self._action_started_at = None
            self._reset_destination(snapshot)
            self._log(logging.INFO, "scenario_runtime.transition")

    @staticmethod
    def _state_changed(
        current: LiveSplitSnapshot,
        received: LiveSplitSnapshot,
    ) -> bool:
        return (
            current.state_revision != received.state_revision
            or current.phase is not received.phase
            or current.split_index != received.split_index
            or current.split_count != received.split_count
        )

    def evaluate(self, context: FrameContext) -> Action | None:
        snapshot = self._snapshot
        if snapshot is None or self._awaiting_resync or not self._configuration_valid:
            return None

        if self._action_started_at is not None:
            elapsed = context.now.nanoseconds - self._action_started_at
            if elapsed < SPLIT_TRANSITION_TIMEOUT_NANOSECONDS:
                return None
            self._reset_destination(snapshot)
            self._action_started_at = None
            self._log(logging.WARNING, "scenario_runtime.transition_timeout")

        if snapshot.phase not in (TimerPhase.RUNNING, TimerPhase.PAUSED):
            return None

        for rule_index, runtime_rule in enumerate(
            self._rules.get(snapshot.split_index, ())
        ):
            try:
                action = runtime_rule.rule.evaluate(context)
            except Exception as error:  # noqa: BLE001
                self._log_rule_exception(
                    error,
                    snapshot,
                    snapshot.split_index,
                    rule_index,
                    runtime_rule.definition,
                )
                continue
            if action is not None:
                self._action_started_at = context.now.nanoseconds
                self._log_rule(
                    logging.INFO,
                    "scenario_runtime.action",
                    snapshot,
                    snapshot.split_index,
                    rule_index,
                    runtime_rule.definition,
                    operation=action.operation,
                )
                return action
        return None

    def _apply_resync(
        self,
        snapshot: LiveSplitSnapshot,
        current: LiveSplitSnapshot,
    ) -> None:
        if snapshot.state_revision < current.state_revision:
            self._log(logging.WARNING, "scenario_runtime.revision_regressed")
            return
        revision_advanced = snapshot.state_revision > current.state_revision
        self._snapshot = snapshot
        self._configuration_valid = self._validate_split_count(snapshot)
        self._awaiting_resync = False
        if revision_advanced:
            self._action_started_at = None
            self._reset_destination(snapshot)
        self._log(
            logging.INFO,
            "scenario_runtime.resynced",
            revision_advanced=revision_advanced,
        )

    def _establish_baseline(self, snapshot: LiveSplitSnapshot) -> None:
        self._snapshot = snapshot
        self._awaiting_resync = False
        self._configuration_valid = self._validate_split_count(snapshot)
        self._log(logging.INFO, "scenario_runtime.baseline")

    def _validate_split_count(self, snapshot: LiveSplitSnapshot) -> bool:
        if snapshot.phase is TimerPhase.NOT_RUNNING and snapshot.split_count == 0:
            return True
        invalid_keys = [
            split_index
            for split_index in self._rules
            if split_index >= snapshot.split_count
        ]
        if invalid_keys:
            self._log(
                logging.ERROR,
                "scenario_runtime.split_count_mismatch",
                invalid_split_indices=tuple(sorted(invalid_keys)),
            )
            return False
        return True

    def _reset_destination(self, snapshot: LiveSplitSnapshot) -> None:
        if snapshot.phase not in (TimerPhase.RUNNING, TimerPhase.PAUSED):
            return
        self._reset_group(snapshot.split_index)

    def _reset_group(self, split_index: int) -> None:
        for rule_index, runtime_rule in enumerate(self._rules.get(split_index, ())):
            try:
                runtime_rule.rule.reset()
            except Exception as error:  # noqa: BLE001
                snapshot = self._snapshot
                if snapshot is not None:
                    self._log_rule_exception(
                        error,
                        snapshot,
                        split_index,
                        rule_index,
                        runtime_rule.definition,
                    )
        self._log(
            logging.DEBUG,
            "scenario_runtime.rules_reset",
            reset_split_index=split_index,
        )

    def _reset_all_rules(self) -> None:
        for split_index in self._rules:
            self._reset_group(split_index)

    def _log_rule_exception(
        self,
        error: Exception,
        snapshot: LiveSplitSnapshot,
        split_index: int,
        rule_index: int,
        definition: RuleDefinition,
    ) -> None:
        self._log_rule(
            logging.ERROR,
            "scenario_runtime.rule_exception",
            snapshot,
            split_index,
            rule_index,
            definition,
            exception_type=type(error).__name__,
            exception_message=str(error),
            exc_info=error,
        )

    def _log_rule(
        self,
        level: int,
        event: str,
        snapshot: LiveSplitSnapshot,
        split_index: int,
        rule_index: int,
        definition: RuleDefinition,
        exc_info: BaseException | bool | None = None,
        **extra: object,
    ) -> None:
        self._log(
            level,
            event,
            split_index=split_index,
            rule_index=rule_index,
            rule_name=definition.name,
            rule_source_path=definition.source_path,
            rule_source_line=definition.source_line,
            session_id=snapshot.session_id,
            state_revision=snapshot.state_revision,
            event_sequence=snapshot.event_sequence,
            exc_info=exc_info,
            **extra,
        )

    def _log(
        self,
        level: int,
        event: str,
        *,
        exc_info: BaseException | bool | None = None,
        **extra: object,
    ) -> None:
        fields: dict[str, object] = {
            "event_name": event,
            "scenario_id": self._definition.scenario_id,
            "target_id": self._definition.target_id,
        }
        snapshot = self._snapshot
        if snapshot is not None:
            fields.update(
                split_index=snapshot.split_index,
                session_id=snapshot.session_id,
                state_revision=snapshot.state_revision,
                event_sequence=snapshot.event_sequence,
            )
        fields.update(extra)
        try:
            self._logger.log(level, event, extra=fields, exc_info=exc_info)
        except Exception:  # noqa: BLE001
            return
