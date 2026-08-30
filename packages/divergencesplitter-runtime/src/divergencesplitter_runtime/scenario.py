"""Evaluation state for one configured scenario."""

import logging

from divergencesplitter.frame.models import FrameContext
from divergencesplitter.rule import Action, Rule
from divergencesplitter.scenario.models import Scenario

from divergencesplitter_runtime.livesplit.models import (
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    TimerPhase,
)

SPLIT_TRANSITION_TIMEOUT_NANOSECONDS = 1_000_000_000


class ScenarioRuntime:
    def __init__(
        self,
        scenario: Scenario,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._scenario = scenario
        self._logger = logger or logging.getLogger(__name__)
        self._reset_rules = tuple(
            Rule(condition=condition, action=Action(operation="reset"))
            for condition in scenario.reset_conditions
        )
        self._snapshot: LiveSplitSnapshot | None = None
        self._awaiting_resync = False
        self._configuration_valid = True
        self._pending_action: Action | None = None
        self._action_started_at: int | None = None

    @property
    def current_snapshot(self) -> LiveSplitSnapshot | None:
        return self._snapshot

    def apply_livesplit_update(self, update: LiveSplitUpdate) -> None:
        snapshot = update.snapshot
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
            self._apply_transition_resets(current, snapshot)
            if (
                self._pending_action is None
                or snapshot.phase is TimerPhase.NOT_RUNNING
                or self._pending_action.operation != "reset"
            ):
                self._clear_pending_action()
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
        if snapshot.phase is TimerPhase.NOT_RUNNING:
            return None
        if (
            self._pending_action is not None
            and self._pending_action.operation == "reset"
        ):
            return None

        reset_action = self._evaluate_rules(
            self._reset_rules,
            context,
            snapshot,
            group="reset",
            split_index=None,
        )
        if reset_action is not None:
            self._start_action(reset_action, context)
            return reset_action

        if self._pending_action is not None:
            if self._action_started_at is None:
                return None
            elapsed = context.now.nanoseconds - self._action_started_at
            if elapsed < SPLIT_TRANSITION_TIMEOUT_NANOSECONDS:
                return None
            self._reset_destination(snapshot)
            self._clear_pending_action()
            self._log(logging.WARNING, "scenario_runtime.transition_timeout")
            return None

        split_index = self._evaluation_index(snapshot)
        if split_index is None or split_index >= len(self._scenario.splits):
            return None
        rules = self._scenario.splits[split_index]
        if rules is None:
            return None
        action = self._evaluate_rules(
            rules,
            context,
            snapshot,
            group="main",
            split_index=split_index,
        )
        if action is not None:
            self._start_action(action, context)
        return action

    def _evaluate_rules(
        self,
        rules: tuple[Rule, ...],
        context: FrameContext,
        snapshot: LiveSplitSnapshot,
        *,
        group: str,
        split_index: int | None,
    ) -> Action | None:
        for rule_index, rule in enumerate(rules):
            try:
                action = rule.evaluate(context)
            except Exception as error:  # noqa: BLE001
                self._log_rule_exception(
                    error, snapshot, group, split_index, rule_index
                )
                continue
            if action is not None:
                self._log_rule(
                    logging.INFO,
                    "scenario_runtime.action",
                    snapshot,
                    group,
                    split_index,
                    rule_index,
                    operation=action.operation,
                )
                return action
        return None

    def _start_action(self, action: Action, context: FrameContext) -> None:
        self._pending_action = action
        self._action_started_at = context.now.nanoseconds

    def _clear_pending_action(self) -> None:
        self._pending_action = None
        self._action_started_at = None

    def _apply_resync(
        self,
        snapshot: LiveSplitSnapshot,
        current: LiveSplitSnapshot,
    ) -> None:
        if snapshot.state_revision < current.state_revision:
            self._log(logging.WARNING, "scenario_runtime.revision_regressed")
            return
        revision_advanced = snapshot.state_revision > current.state_revision
        run_changed = snapshot.split_count != current.split_count
        self._snapshot = snapshot
        self._configuration_valid = self._validate_split_count(snapshot)
        self._awaiting_resync = False
        self._clear_pending_action()
        if revision_advanced or run_changed:
            self._reset_all_rules()
        self._log(
            logging.INFO,
            "scenario_runtime.resynced",
            revision_advanced=revision_advanced,
            run_changed=run_changed,
        )

    def _establish_baseline(self, snapshot: LiveSplitSnapshot) -> None:
        self._snapshot = snapshot
        self._awaiting_resync = False
        self._configuration_valid = self._validate_split_count(snapshot)
        self._clear_pending_action()
        self._reset_all_rules()
        self._log(logging.INFO, "scenario_runtime.baseline")

    def _validate_split_count(self, snapshot: LiveSplitSnapshot) -> bool:
        if snapshot.phase is TimerPhase.NOT_RUNNING and snapshot.split_count == 0:
            return True
        if len(self._scenario.splits) > snapshot.split_count + 1:
            self._log(
                logging.ERROR,
                "scenario_runtime.split_count_mismatch",
                configured_split_slots=len(self._scenario.splits),
                maximum_split_slots=snapshot.split_count + 1,
            )
            return False
        return True

    @staticmethod
    def _evaluation_index(snapshot: LiveSplitSnapshot) -> int | None:
        if snapshot.phase in (TimerPhase.RUNNING, TimerPhase.PAUSED):
            return snapshot.split_index
        if snapshot.phase is TimerPhase.ENDED:
            return snapshot.split_count
        return None

    def _apply_transition_resets(
        self,
        current: LiveSplitSnapshot,
        snapshot: LiveSplitSnapshot,
    ) -> None:
        if (
            snapshot.phase is TimerPhase.NOT_RUNNING
            or snapshot.split_count != current.split_count
        ):
            self._reset_all_rules()
            return
        destination = self._evaluation_index(snapshot)
        if destination is not None and (
            destination != self._evaluation_index(current)
            or snapshot.phase is current.phase
        ):
            self._reset_group(destination)

    def _reset_destination(self, snapshot: LiveSplitSnapshot) -> None:
        split_index = self._evaluation_index(snapshot)
        if split_index is not None:
            self._reset_group(split_index)

    def _reset_group(self, split_index: int) -> None:
        if split_index >= len(self._scenario.splits):
            return
        rules = self._scenario.splits[split_index]
        if rules is None:
            return
        for rule_index, rule in enumerate(rules):
            try:
                rule.reset()
            except Exception as error:  # noqa: BLE001
                snapshot = self._snapshot
                if snapshot is not None:
                    self._log_rule_exception(
                        error, snapshot, "main", split_index, rule_index
                    )
        self._log(
            logging.DEBUG,
            "scenario_runtime.rules_reset",
            reset_split_index=split_index,
        )

    def _reset_all_rules(self) -> None:
        snapshot = self._snapshot
        for rule_index, rule in enumerate(self._reset_rules):
            try:
                rule.reset()
            except Exception as error:  # noqa: BLE001
                if snapshot is not None:
                    self._log_rule_exception(error, snapshot, "reset", None, rule_index)
        for split_index in range(len(self._scenario.splits)):
            self._reset_group(split_index)

    def _log_rule_exception(
        self,
        error: Exception,
        snapshot: LiveSplitSnapshot,
        group: str,
        split_index: int | None,
        rule_index: int,
    ) -> None:
        self._log_rule(
            logging.ERROR,
            "scenario_runtime.rule_exception",
            snapshot,
            group,
            split_index,
            rule_index,
            exception_type=type(error).__name__,
            exception_message=str(error),
            exc_info=error,
        )

    def _log_rule(
        self,
        level: int,
        event: str,
        snapshot: LiveSplitSnapshot,
        group: str,
        split_index: int | None,
        rule_index: int,
        exc_info: BaseException | bool | None = None,
        **extra: object,
    ) -> None:
        self._log(
            level,
            event,
            rule_group=group,
            rule_split_index=split_index,
            rule_index=rule_index,
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
        fields: dict[str, object] = {"event_name": event}
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
