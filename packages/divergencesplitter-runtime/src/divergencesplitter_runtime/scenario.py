"""Evaluation state for one configured scenario."""

import logging
import re
from typing import NotRequired, TypedDict

from divergencesplitter.condition import Detected
from divergencesplitter.detector.models import DetectionResult
from divergencesplitter.frame.models import FrameContext
from divergencesplitter.rule import Action, Rule, RuleSequence, ScenarioRule
from divergencesplitter.scenario.models import Scenario

from divergencesplitter_runtime.livesplit.models import (
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    TimerPhase,
)

SPLIT_TRANSITION_TIMEOUT_NANOSECONDS = 1_000_000_000


class _RuleEvaluationFields(TypedDict):
    condition_type: NotRequired[str]
    detector_type: NotRequired[str]
    detector_minimum_score: NotRequired[float]
    detector_cache_hit: NotRequired[bool]
    detector_score: NotRequired[float | None]
    sequence_rule_index: NotRequired[int]


class ScenarioRuntime:
    def __init__(
        self,
        scenario: Scenario,
        *,
        logger: logging.Logger | logging.LoggerAdapter | None = None,
    ) -> None:
        self._scenario = scenario
        self._logger = logger or logging.getLogger(__name__)
        self._start_rules = (Rule(scenario.start_condition, Action("start")),)
        self._reset_rules = (
            ()
            if scenario.reset_condition is None
            else (Rule(scenario.reset_condition, Action("reset")),)
        )
        self._incomplete_rules = (
            ()
            if scenario.incomplete_condition is None
            else (Rule(scenario.incomplete_condition, Action("undo")),)
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

        # An RPC resync can confirm the same sequence: no new event is required
        # to release a synchronization wait or refresh the authoritative state.
        if update.kind is LiveSplitUpdateKind.RESYNC:
            if snapshot.event_sequence < current.event_sequence:
                self._log(logging.DEBUG, "scenario_runtime.update_ignored")
                return
            self._apply_resync(snapshot, current)
            return

        if snapshot.event_sequence <= current.event_sequence:
            self._log(logging.DEBUG, "scenario_runtime.update_ignored")
            return

        if update.kind is LiveSplitUpdateKind.INITIAL:
            self._log(logging.WARNING, "scenario_runtime.initial_update_ignored")
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
            self._clear_pending_action()
            self._log(
                logging.INFO,
                "scenario_runtime.transition",
                previous_phase=current.phase.name,
                previous_split_index=current.split_index,
                previous_split_count=current.split_count,
                previous_state_revision=current.state_revision,
                previous_event_sequence=current.event_sequence,
            )

    @staticmethod
    def _state_changed(
        current: LiveSplitSnapshot,
        received: LiveSplitSnapshot,
    ) -> bool:
        return (
            # Game-time events advance the revision without changing which
            # scenario rules should run. They are valid PERIODIC updates.
            current.phase is not received.phase
            or current.split_index != received.split_index
            or current.split_count != received.split_count
        )

    def evaluate(self, context: FrameContext) -> Action | None:
        snapshot = self._snapshot
        if snapshot is None or self._awaiting_resync or not self._configuration_valid:
            return None

        if self._pending_action is not None and self._pending_action.operation in {
            "split",
            "skip",
        }:
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
            self._reset_pending_action(snapshot)
            action_started_at = self._action_started_at
            self._clear_pending_action()
            self._log(
                logging.WARNING,
                "scenario_runtime.transition_timeout",
                action_started_at_ns=action_started_at,
                action_deadline_ns=(
                    None
                    if action_started_at is None
                    else action_started_at + SPLIT_TRANSITION_TIMEOUT_NANOSECONDS
                ),
                observed_at_ns=context.now.nanoseconds,
            )
            return None

        if snapshot.phase is TimerPhase.NOT_RUNNING:
            rules, group = self._start_rules, "start"
        elif snapshot.phase is TimerPhase.STARTING:
            return None
        elif snapshot.phase is TimerPhase.ENDED:
            rules, group = self._incomplete_rules, "incomplete"
        else:
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
            rules, group = (), "main"

        if group != "main":
            action = self._evaluate_rules(
                rules, context, snapshot, group=group, split_index=None
            )
            if action is not None:
                self._start_action(action, context)
            return action

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

    def _reset_pending_action(self, snapshot: LiveSplitSnapshot) -> None:
        action = self._pending_action
        if action is None:
            return
        if action.operation == "start":
            self._reset_rule_group(self._start_rules, "start", None)
        elif action.operation == "undo":
            self._reset_rule_group(self._incomplete_rules, "incomplete", None)
        elif action.operation == "reset":
            self._reset_rule_group(self._reset_rules, "reset", None)
        else:
            split_index = self._evaluation_index(snapshot)
            if split_index is not None:
                self._reset_split_group(split_index)

    def _evaluate_rules(
        self,
        rules: tuple[ScenarioRule, ...],
        context: FrameContext,
        snapshot: LiveSplitSnapshot,
        *,
        group: str,
        split_index: int | None,
    ) -> Action | None:
        for rule_index, rule in enumerate(rules):
            leaf_rule, sequence_rule_index = _active_rule_metadata(rule)
            evaluation_fields = _rule_evaluation_fields(
                leaf_rule, sequence_rule_index, context
            )
            try:
                action = rule.evaluate(context)
            except Exception as error:  # noqa: BLE001
                self._log_rule_exception(
                    error,
                    rule,
                    snapshot,
                    group,
                    split_index,
                    rule_index,
                    **evaluation_fields,
                )
                continue
            evaluation_fields.update(_rule_evaluation_result_fields(leaf_rule, context))
            self._log_rule(
                logging.DEBUG,
                "scenario_runtime.rule_evaluated",
                snapshot,
                group,
                split_index,
                rule_index,
                **evaluation_fields,
                matched=action is not None,
            )
            if action is not None:
                self._log_rule(
                    logging.INFO,
                    "scenario_runtime.action",
                    snapshot,
                    group,
                    split_index,
                    rule_index,
                    operation=action.operation,
                    action_started_at_ns=context.now.nanoseconds,
                    action_deadline_ns=(
                        context.now.nanoseconds + SPLIT_TRANSITION_TIMEOUT_NANOSECONDS
                    ),
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
        if len(self._scenario.splits) > snapshot.split_count:
            self._log(
                logging.ERROR,
                "scenario_runtime.split_count_mismatch",
                configured_split_slots=len(self._scenario.splits),
                maximum_split_slots=snapshot.split_count,
            )
            return False
        return True

    @staticmethod
    def _evaluation_index(snapshot: LiveSplitSnapshot) -> int | None:
        if snapshot.phase in (TimerPhase.RUNNING, TimerPhase.PAUSED):
            return snapshot.split_index
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
        if current.phase is TimerPhase.ENDED and snapshot.phase in (
            TimerPhase.RUNNING,
            TimerPhase.PAUSED,
        ):
            self._reset_rule_group(self._incomplete_rules, "incomplete", None)
            self._reset_rule_group(self._reset_rules, "reset", None)
        elif snapshot.phase is TimerPhase.ENDED:
            self._reset_rule_group(self._incomplete_rules, "incomplete", None)
            return
        destination = self._evaluation_index(snapshot)
        if destination is not None and (
            destination != self._evaluation_index(current)
            or snapshot.phase is current.phase
        ):
            self._reset_split_group(destination)

    def _reset_split_group(self, split_index: int) -> None:
        if split_index >= len(self._scenario.splits):
            return
        rules = self._scenario.splits[split_index]
        if rules is None:
            return
        self._reset_rule_group(rules, "main", split_index)

    def _reset_rule_group(
        self,
        rules: tuple[ScenarioRule, ...],
        group: str,
        split_index: int | None,
    ) -> None:
        for rule_index, rule in enumerate(rules):
            try:
                rule.reset()
            except Exception as error:  # noqa: BLE001
                snapshot = self._snapshot
                if snapshot is not None:
                    self._log_rule_exception(
                        error,
                        rule,
                        snapshot,
                        group,
                        split_index,
                        rule_index,
                    )
        self._log(
            logging.DEBUG,
            "scenario_runtime.rules_reset",
            reset_split_index=split_index,
        )

    def _reset_all_rules(self) -> None:
        self._reset_rule_group(self._start_rules, "start", None)
        self._reset_rule_group(self._reset_rules, "reset", None)
        self._reset_rule_group(self._incomplete_rules, "incomplete", None)
        for split_index in range(len(self._scenario.splits)):
            self._reset_split_group(split_index)

    def _log_rule_exception(
        self,
        error: Exception,
        rule: ScenarioRule,
        snapshot: LiveSplitSnapshot,
        group: str,
        split_index: int | None,
        rule_index: int,
        **extra: object,
    ) -> None:
        leaf_rule, sequence_rule_index = _active_rule_metadata(rule)
        if leaf_rule is not None:
            extra.setdefault("condition_type", type(leaf_rule.condition).__name__)
        if sequence_rule_index is not None:
            extra.setdefault("sequence_rule_index", sequence_rule_index)
        self._log_rule(
            logging.ERROR,
            "scenario_runtime.rule_exception",
            snapshot,
            group,
            split_index,
            rule_index,
            exception_type=type(error).__name__,
            exception_message=_safe_exception_message(error),
            exc_info=error,
            **extra,
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
                phase=snapshot.phase.name,
                split_count=snapshot.split_count,
            )
        fields.update(extra)
        try:
            self._logger.log(level, event, extra=fields, exc_info=exc_info)
        except Exception:  # noqa: BLE001
            return


def _safe_exception_message(error: Exception) -> str:
    try:
        return re.sub(
            r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@",
            r"\g<scheme>",
            str(error),
        )
    except Exception:  # noqa: BLE001
        return f"<{type(error).__name__} could not be formatted>"


def _rule_evaluation_fields(
    rule: Rule | None,
    sequence_rule_index: int | None,
    context: FrameContext,
) -> _RuleEvaluationFields:
    fields = _RuleEvaluationFields()
    if sequence_rule_index is not None:
        fields["sequence_rule_index"] = sequence_rule_index
    if rule is None:
        return fields
    fields["condition_type"] = type(rule.condition).__name__
    if isinstance(rule.condition, Detected):
        fields.update(
            detector_type=type(rule.condition.detector).__name__,
            detector_minimum_score=rule.condition.minimum_score,
            detector_cache_hit=rule.condition.detector in context.detection_cache,
        )
    return fields


def _rule_evaluation_result_fields(
    rule: Rule | None,
    context: FrameContext,
) -> _RuleEvaluationFields:
    if rule is None or not isinstance(rule.condition, Detected):
        return {}
    result = context.detection_cache.get(rule.condition.detector)
    return {
        "detector_score": result.score if isinstance(result, DetectionResult) else None
    }


def _active_rule_metadata(
    rule: ScenarioRule,
) -> tuple[Rule | None, int | None]:
    if isinstance(rule, RuleSequence):
        return rule.active_rule, rule.active_rule_index
    if isinstance(rule, Rule):
        return rule, None
    return None, None
