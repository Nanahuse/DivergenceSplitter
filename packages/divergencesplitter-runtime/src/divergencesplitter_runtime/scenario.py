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
    LiveSplitTransitionReason,
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
        self._session_id: int | None = None
        self._event_sequence: int | None = None
        self._state_epoch = 0
        self._configuration_valid = True
        # Normal actions (start/split/skip/undo/pause/resume) and Reset are
        # tracked separately: a rejected Reset must not lose a pending Split,
        # and a stale Split event must not release a pending Reset.
        self._pending_action: Action | None = None
        self._action_started_at: int | None = None
        self._state_wait_started_at: int | None = None
        self._reset_pending: Action | None = None
        self._reset_started_at: int | None = None
        self._reset_state_wait_started_at: int | None = None

    @property
    def current_snapshot(self) -> LiveSplitSnapshot | None:
        return self._snapshot

    @property
    def state_epoch(self) -> int:
        return self._state_epoch

    @property
    def state_wait_deadline_ns(self) -> int | None:
        deadlines: list[int] = []
        if self._state_wait_started_at is not None:
            deadlines.append(
                self._state_wait_started_at + SPLIT_TRANSITION_TIMEOUT_NANOSECONDS
            )
        if self._reset_state_wait_started_at is not None:
            deadlines.append(
                self._reset_state_wait_started_at + SPLIT_TRANSITION_TIMEOUT_NANOSECONDS
            )
        if not deadlines:
            return None
        return min(deadlines)

    def apply_livesplit_update(self, update: LiveSplitUpdate) -> None:
        snapshot = update.snapshot
        current = self._snapshot
        if current is None:
            if update.kind is not LiveSplitUpdateKind.INITIAL:
                self._log(logging.WARNING, "scenario_runtime.initial_sync_required")
                return
            self._establish_baseline(update)
            return

        if update.session_id != self._session_id:
            # A changed session is recovered by reconnecting to a fresh runtime;
            # never apply cross-session state onto the current rules.
            self._log(
                logging.WARNING,
                "scenario_runtime.session_resync_required",
                received_session_id=update.session_id,
            )
            return

        if update.kind is LiveSplitUpdateKind.INITIAL:
            self._log(logging.WARNING, "scenario_runtime.initial_update_ignored")
            return

        run_changed = update.run_structure_changed
        self._snapshot = snapshot
        self._session_id = update.session_id
        self._event_sequence = update.event_sequence
        self._state_epoch = update.state_epoch
        self._configuration_valid = self._validate_split_count(snapshot)
        if update.kind is LiveSplitUpdateKind.TRANSITION or run_changed:
            if run_changed:
                self._reset_all_rules()
                self._clear_all_pending()
            else:
                self._apply_transition_resets(current, snapshot)
                self._resolve_transition_pending(update.transition)
            self._log(
                logging.INFO,
                "scenario_runtime.transition",
                previous_phase=current.phase.name,
                previous_split_index=current.split_index,
                previous_split_count=current.split_count,
                state_epoch=update.state_epoch,
            )

    def evaluate(self, context: FrameContext) -> Action | None:
        snapshot = self._snapshot
        if snapshot is None or not self._configuration_valid:
            return None

        # While a Reset wait is unresolved it blocks every new control so a
        # stale normal action can never be issued before the Reset resolves.
        if self._reset_pending is not None:
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
            return None

        if snapshot.phase is TimerPhase.NOT_RUNNING:
            rules, group = self._start_rules, "start"
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

    def action_not_dispatched(self, action: Action) -> None:
        """Release a pending action that was never sent to LiveSplit.

        Called when a locally rejected (stale or precondition-failing) action
        leaves ``evaluate`` with a pending action set. The rule progress the
        action advanced is reset so the next frame can decide again.
        """
        if action.operation == "reset":
            # A Reset that was never sent keeps no Reset wait; restore its rules
            # so an automatic Reset can be decided again. The pending normal
            # action is deliberately left untouched.
            self._clear_reset_pending()
            self._reset_rule_group(self._reset_rules, "reset", None)
            return
        if self._pending_action is None:
            return
        snapshot = self._snapshot
        if snapshot is not None:
            self._reset_pending_action(snapshot)
        self._clear_pending_action()

    def action_accepted(self, action: Action, accepted_at_ns: int) -> None:
        """Start the Bridge state wait only after a successful Control response."""
        if action.operation == "reset":
            if self._reset_pending is None:
                return
            self._reset_state_wait_started_at = accepted_at_ns
            # A successful Reset absorbs the preceding normal wait; the Reset
            # wait itself stays pending until an authoritative Reset event.
            self._clear_pending_action()
            return
        if self._pending_action != action:
            return
        self._state_wait_started_at = accepted_at_ns

    def cancel_pending_action(self) -> Action | None:
        """Drop an unsent normal action and restart the rules it advanced.

        Used when a Reset supersedes a normal action during a reaction wait so
        no stale rule progress or pending action survives.
        """
        action = self._pending_action
        if action is None:
            return None
        snapshot = self._snapshot
        if snapshot is not None:
            self._reset_pending_action(snapshot)
        self._clear_pending_action()
        return action

    @property
    def pending_action(self) -> Action | None:
        return self._pending_action

    @property
    def reset_pending(self) -> Action | None:
        return self._reset_pending

    def external_action_pending(self, action: Action, decided_at_ns: int) -> None:
        """Track a manual Reset in the dedicated Reset wait.

        Any pending normal action is preserved so a rejected Reset can restore
        it rather than silently losing the wait.
        """
        self._reset_pending = action
        self._reset_started_at = decided_at_ns
        self._reset_state_wait_started_at = None

    def settle_rejected_reset(self, update: LiveSplitUpdate) -> None:
        """Adopt the authoritative state after a Reset was rejected.

        The rejected Reset and any preceding normal wait are dropped, the queried
        snapshot becomes the current state, and the rules the current phase and
        split index evaluate from are restarted through their normal ``reset()``.
        The rejected Reset is never retried here; a later frame may still decide
        a fresh Reset through the ordinary rule evaluation.
        """
        snapshot = update.snapshot
        self._snapshot = snapshot
        self._session_id = update.session_id
        self._event_sequence = update.event_sequence
        self._state_epoch = update.state_epoch
        self._configuration_valid = self._validate_split_count(snapshot)
        self._clear_all_pending()
        self._restart_rules_for_snapshot(snapshot)
        self._log(
            logging.INFO,
            "scenario_runtime.reset_rejected_reconciled",
            state_epoch=update.state_epoch,
        )

    def _restart_rules_for_snapshot(self, snapshot: LiveSplitSnapshot) -> None:
        # The rejected Reset may be decided again from a clean condition state,
        # plus the rules the current phase and split index evaluate from.
        self._reset_rule_group(self._reset_rules, "reset", None)
        if snapshot.phase is TimerPhase.NOT_RUNNING:
            self._reset_rule_group(self._start_rules, "start", None)
        elif snapshot.phase is TimerPhase.ENDED:
            self._reset_rule_group(self._incomplete_rules, "incomplete", None)
        else:
            split_index = self._evaluation_index(snapshot)
            if split_index is not None:
                self._reset_split_group(split_index)

    def evaluate_reset_only(self, context: FrameContext) -> Action | None:
        """Evaluate only the Reset condition during a reaction wait.

        The frame is used solely to honor Reset priority over the pending
        normal action, so it is never reused for that normal action.
        """
        snapshot = self._snapshot
        if snapshot is None or not self._configuration_valid:
            return None
        if self._reset_pending is not None:
            return None
        if snapshot.phase not in (TimerPhase.RUNNING, TimerPhase.PAUSED):
            return None
        action = self._evaluate_rules(
            self._reset_rules,
            context,
            snapshot,
            group="reset",
            split_index=None,
        )
        if action is not None:
            self._start_action(action, context)
        return action

    def state_wait_timed_out(self, observed_at_ns: int) -> None:
        """Release any state wait whose deadline has passed."""
        resolved = False
        if (
            self._pending_action is not None
            and self._state_wait_started_at is not None
            and observed_at_ns
            >= self._state_wait_started_at + SPLIT_TRANSITION_TIMEOUT_NANOSECONDS
        ):
            action = self._pending_action
            snapshot = self._snapshot
            if snapshot is not None:
                if action.operation in ("split", "skip"):
                    split_index = self._evaluation_index(snapshot)
                    if split_index is not None:
                        self._reset_split_group(split_index)
                        self._log(
                            logging.WARNING,
                            "scenario_runtime.same_index_reentry",
                            split_index=split_index,
                            state_epoch=self._state_epoch,
                        )
                else:
                    self._reset_pending_action(snapshot)
            self._clear_pending_action()
            resolved = True
        if (
            self._reset_pending is not None
            and self._reset_state_wait_started_at is not None
            and observed_at_ns
            >= self._reset_state_wait_started_at + SPLIT_TRANSITION_TIMEOUT_NANOSECONDS
        ):
            self._reset_rule_group(self._reset_rules, "reset", None)
            self._clear_reset_pending()
            resolved = True
        if resolved:
            self._log(
                logging.WARNING,
                "scenario_runtime.transition_timeout",
                observed_at_ns=observed_at_ns,
            )

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
        if action.operation == "reset":
            # A Reset supersedes any pending normal action. Restart that
            # action's rules so no stale progress survives the Reset.
            snapshot = self._snapshot
            if self._pending_action is not None and snapshot is not None:
                self._reset_pending_action(snapshot)
            self._clear_pending_action()
            self._reset_pending = action
            self._reset_started_at = context.now.nanoseconds
            self._reset_state_wait_started_at = None
            return
        self._pending_action = action
        self._action_started_at = context.now.nanoseconds

    def _clear_pending_action(self) -> None:
        self._pending_action = None
        self._action_started_at = None
        self._state_wait_started_at = None

    def _clear_reset_pending(self) -> None:
        self._reset_pending = None
        self._reset_started_at = None
        self._reset_state_wait_started_at = None

    def _clear_all_pending(self) -> None:
        self._clear_pending_action()
        self._clear_reset_pending()

    def _resolve_transition_pending(
        self,
        reason: LiveSplitTransitionReason | None,
    ) -> None:
        """Resolve state waits from an accepted transition, not from any event.

        ``None`` is an authoritative query result (already-confirmed state), so
        it resolves both waits. A Reset transition resolves both. Pause/Resume
        must not complete a pending Split/Skip wait, and Split/Skip/Start/Undo
        must not release a pending Reset.
        """
        if reason is None or reason is LiveSplitTransitionReason.RESET:
            self._clear_all_pending()
            return
        if reason in (
            LiveSplitTransitionReason.PAUSE,
            LiveSplitTransitionReason.RESUME,
        ):
            if self._pending_action is not None and self._pending_action.operation in (
                "pause",
                "resume",
            ):
                self._clear_pending_action()
            return
        self._clear_pending_action()

    def _establish_baseline(self, update: LiveSplitUpdate) -> None:
        snapshot = update.snapshot
        self._snapshot = snapshot
        self._session_id = update.session_id
        self._event_sequence = update.event_sequence
        self._state_epoch = update.state_epoch
        self._configuration_valid = self._validate_split_count(snapshot)
        self._clear_all_pending()
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
        elif current.phase is TimerPhase.NOT_RUNNING and snapshot.phase in (
            TimerPhase.RUNNING,
            TimerPhase.PAUSED,
        ):
            self._reset_rule_group(self._start_rules, "start", None)
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
            session_id=self._session_id,
            event_sequence=self._event_sequence,
            state_epoch=self._state_epoch,
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
                session_id=self._session_id,
                event_sequence=self._event_sequence,
                state_epoch=self._state_epoch,
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
            detector_cache_hit=context.cache.has_detection(rule.condition.detector),
        )
    return fields


def _rule_evaluation_result_fields(
    rule: Rule | None,
    context: FrameContext,
) -> _RuleEvaluationFields:
    if rule is None or not isinstance(rule.condition, Detected):
        return {}
    result = context.cache.cached_detection(rule.condition.detector)
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
