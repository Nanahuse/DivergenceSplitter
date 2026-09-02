from __future__ import annotations

import threading
from collections import deque
from typing import ClassVar, Literal, overload

import numpy as np
from divergencesplitter import (
    Action,
    ErrorAction,
    Frame,
    FrameContext,
    FrameSourceState,
    LiveSplitConnection,
    MonotonicTime,
)
from divergencesplitter_runtime import (
    ActionSubmission,
    BridgeActionRequest,
    LiveSplitResyncReason,
    LiveSplitSnapshot,
    LiveSplitUpdate,
    LiveSplitUpdateKind,
    PublishResult,
    TimerPhase,
)
from livesplit_bridge import BridgeConnectionLostError


def snapshot(
    *,
    session_id: int = 1,
    state_revision: int = 0,
    event_sequence: int = 0,
    phase: TimerPhase = TimerPhase.RUNNING,
    split_index: int = 0,
    split_count: int = 1,
) -> LiveSplitSnapshot:
    return LiveSplitSnapshot(
        session_id=session_id,
        state_revision=state_revision,
        event_sequence=event_sequence,
        phase=phase,
        split_index=split_index,
        split_count=split_count,
    )


class BridgeScript:
    """Thread-safe LiveSplit authority used by the Adapter test double."""

    def __init__(
        self,
        initial_snapshot: LiveSplitSnapshot,
        *,
        apply_actions: bool = True,
    ) -> None:
        self._condition = threading.Condition()
        self._events: deque[LiveSplitUpdate | LiveSplitResyncReason | Exception] = (
            deque()
        )
        self._snapshot = initial_snapshot
        self._apply_actions = apply_actions
        self.actions: list[tuple[Action, LiveSplitSnapshot]] = []
        self.action_threads: list[int] = []
        self.snapshot_mismatches: list[tuple[LiveSplitSnapshot, LiveSplitSnapshot]] = []
        self.created_on: int | None = None
        self.closed_on: int | None = None
        self.closed = threading.Event()
        self.ended = threading.Event()
        self.resync_entered = threading.Event()
        self._resync_release = threading.Event()
        self._block_resync = False

    @property
    def current_snapshot(self) -> LiveSplitSnapshot:
        with self._condition:
            return self._snapshot

    def attach(self) -> LiveSplitUpdate:
        with self._condition:
            return LiveSplitUpdate(LiveSplitUpdateKind.INITIAL, self._snapshot)

    def receive(
        self,
        *,
        timeout_ms: int | None,
    ) -> LiveSplitUpdate | LiveSplitResyncReason | None:
        timeout_seconds = None if timeout_ms is None else timeout_ms / 1000
        with self._condition:
            self._condition.wait_for(
                lambda: bool(self._events) or self.closed.is_set(),
                timeout_seconds,
            )
            if not self._events:
                return None
            item = self._events.popleft()
        if isinstance(item, Exception):
            raise item
        return item

    def execute_action(
        self,
        action: Action,
        expected_snapshot: LiveSplitSnapshot,
    ) -> None:
        with self._condition:
            actual = self._snapshot
            self.actions.append((action, expected_snapshot))
            self.action_threads.append(threading.get_ident())
            if expected_snapshot != actual:
                self.snapshot_mismatches.append((expected_snapshot, actual))
                self._condition.notify_all()
                return
            if self._apply_actions:
                self._apply_action_locked(action)
            self._condition.notify_all()

    def resync(self, reason: LiveSplitResyncReason) -> LiveSplitUpdate:
        del reason
        if self._block_resync:
            self.resync_entered.set()
            if not self._resync_release.wait(5):
                raise TimeoutError("test did not release Bridge resynchronization")
        with self._condition:
            return LiveSplitUpdate(LiveSplitUpdateKind.RESYNC, self._snapshot)

    def reconnect(self) -> LiveSplitUpdate:
        return self.resync(LiveSplitResyncReason.CONNECTION_LOST)

    def block_resync(self) -> None:
        self._block_resync = True
        self._resync_release.clear()
        self.resync_entered.clear()

    def release_resync(self) -> None:
        self._resync_release.set()

    def inject_gap(self) -> None:
        self._enqueue(LiveSplitResyncReason.GAP)

    def inject_connection_loss(self) -> None:
        self._enqueue(BridgeConnectionLostError("test connection lost"))

    def external_undo(self) -> None:
        with self._condition:
            current = self._snapshot
            if current.phase is TimerPhase.ENDED:
                split_index = current.split_count - 1
            else:
                split_index = current.split_index - 1
            self._publish_transition_locked(
                phase=TimerPhase.RUNNING,
                split_index=split_index,
            )
            self._condition.notify_all()

    def wait_for_actions(self, count: int, timeout_seconds: float) -> bool:
        with self._condition:
            return self._condition.wait_for(
                lambda: len(self.actions) >= count,
                timeout_seconds,
            )

    def close(self) -> None:
        self.closed_on = threading.get_ident()
        self.closed.set()
        with self._condition:
            self._condition.notify_all()

    def _enqueue(
        self,
        item: LiveSplitUpdate | LiveSplitResyncReason | Exception,
    ) -> None:
        with self._condition:
            self._events.append(item)
            self._condition.notify_all()

    def _apply_action_locked(self, action: Action) -> None:
        current = self._snapshot
        if action.operation == "split":
            destination = current.split_index + 1
            phase = (
                TimerPhase.ENDED
                if destination == current.split_count
                else TimerPhase.RUNNING
            )
            self._publish_transition_locked(phase=phase, split_index=destination)
            if phase is TimerPhase.ENDED:
                self.ended.set()
            return
        if action.operation == "undo":
            destination = (
                current.split_count - 1
                if current.phase is TimerPhase.ENDED
                else current.split_index - 1
            )
            self._publish_transition_locked(
                phase=TimerPhase.RUNNING,
                split_index=destination,
            )
            return
        if action.operation == "reset":
            self._publish_transition_locked(
                phase=TimerPhase.NOT_RUNNING,
                split_index=-1,
            )

    def _publish_transition_locked(
        self,
        *,
        phase: TimerPhase,
        split_index: int,
    ) -> None:
        current = self._snapshot
        self._snapshot = snapshot(
            session_id=current.session_id,
            state_revision=current.state_revision + 1,
            event_sequence=current.event_sequence + 1,
            phase=phase,
            split_index=split_index,
            split_count=current.split_count,
        )
        self._events.append(
            LiveSplitUpdate(LiveSplitUpdateKind.TRANSITION, self._snapshot)
        )


class ScriptedBridgeAdapter:
    """Adapter-shaped test double selected by LiveSplitConnection."""

    scripts: ClassVar[dict[LiveSplitConnection, BridgeScript]] = {}

    def __init__(
        self,
        connection: LiveSplitConnection,
        **_: object,
    ) -> None:
        self._script = self.scripts[connection]
        self._script.created_on = threading.get_ident()

    def attach(self) -> LiveSplitUpdate:
        return self._script.attach()

    def receive(
        self,
        *,
        timeout_ms: int | None = None,
    ) -> LiveSplitUpdate | LiveSplitResyncReason | None:
        return self._script.receive(timeout_ms=timeout_ms)

    def execute_action(
        self,
        action: Action,
        expected_snapshot: LiveSplitSnapshot,
    ) -> None:
        self._script.execute_action(action, expected_snapshot)

    def resync(self, reason: LiveSplitResyncReason) -> LiveSplitUpdate:
        return self._script.resync(reason)

    def reconnect(self) -> LiveSplitUpdate:
        return self._script.reconnect()

    def close(self) -> None:
        self._script.close()


class RecordingDiagnostics:
    def __init__(self, *, bright_threshold: float = 128) -> None:
        self.publish_results: list[PublishResult] = []
        self.scenario_errors: list[Exception] = []
        self.connection_errors: list[Exception] = []
        self.first_frame_started = threading.Event()
        self.bright_frame_started = threading.Event()
        self.frame_overwritten = threading.Event()
        self.source_closed_event = threading.Event()
        self.capture_stopped = threading.Event()
        self.worker_stopped_event = threading.Event()
        self._bright_threshold = bright_threshold

    def preparing(self) -> None:
        pass

    def prepared(self) -> None:
        pass

    def frame_received(self, publish_result: PublishResult) -> None:
        self.publish_results.append(publish_result)
        if publish_result is PublishResult.OVERWROTE:
            self.frame_overwritten.set()

    def source_error(self, error: object) -> None:
        pass

    def error_handled(self, action: ErrorAction, state: FrameSourceState) -> None:
        pass

    def source_state_changed(
        self,
        previous: FrameSourceState | None,
        current: FrameSourceState,
    ) -> None:
        pass

    def source_state_unavailable(self, error: Exception) -> None:
        pass

    def source_closed(self) -> None:
        self.source_closed_event.set()

    def stopped(self) -> None:
        self.capture_stopped.set()

    def frame_processing_started(
        self,
        frame: Frame,
        processing_started_at: MonotonicTime,
    ) -> None:
        del processing_started_at
        self.first_frame_started.set()
        if float(np.mean(frame.image)) >= self._bright_threshold:
            self.bright_frame_started.set()

    def scenario_evaluation_failed(
        self,
        scenario_index: int,
        error: Exception,
    ) -> None:
        del scenario_index
        self.scenario_errors.append(error)

    def worker_started(self, connection: LiveSplitConnection) -> None:
        pass

    def initial_sync_failed(
        self,
        connection: LiveSplitConnection,
        error: Exception,
    ) -> None:
        self.connection_errors.append(error)

    def connection_lost(
        self,
        connection: LiveSplitConnection,
        error: Exception,
    ) -> None:
        self.connection_errors.append(error)

    def reconnect_failed(
        self,
        connection: LiveSplitConnection,
        error: Exception,
    ) -> None:
        self.connection_errors.append(error)

    def update_queue_overflowed(self, connection: LiveSplitConnection) -> None:
        pass

    def action_submitted(
        self,
        connection: LiveSplitConnection,
        request: BridgeActionRequest,
        result: ActionSubmission,
    ) -> None:
        pass

    def worker_stopped(self, connection: LiveSplitConnection) -> None:
        self.worker_stopped_event.set()

    def snapshot_failed(self, action: Action, error: Exception) -> None:
        pass

    def snapshot_mismatched(
        self,
        action: Action,
        expected: LiveSplitSnapshot,
        actual: LiveSplitSnapshot,
    ) -> None:
        pass

    def action_precondition_failed(
        self,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None:
        pass

    def action_succeeded(
        self,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None:
        pass

    def action_rejected(
        self,
        action: Action,
        snapshot: LiveSplitSnapshot,
        code: int | None,
        message: str,
    ) -> None:
        pass

    def action_result_unknown(
        self,
        action: Action,
        snapshot: LiveSplitSnapshot,
        error: Exception,
    ) -> None:
        pass

    def gap_detected(
        self,
        connection: LiveSplitConnection,
        baseline: LiveSplitSnapshot,
        received_session_id: int,
        received_event_sequence: int,
    ) -> None:
        pass

    def heartbeat_received(
        self,
        connection: LiveSplitConnection,
        session_id: int,
        event_sequence: int,
    ) -> None:
        pass

    def resync_started(
        self,
        connection: LiveSplitConnection,
        reason: LiveSplitResyncReason,
    ) -> None:
        pass

    def resync_completed(
        self,
        connection: LiveSplitConnection,
        reason: LiveSplitResyncReason,
        previous: LiveSplitSnapshot,
        current: LiveSplitSnapshot,
    ) -> None:
        pass


class BlockingDetectedCondition:
    """Block the first evaluation until the test observes a buffer overwrite."""

    def __init__(self, threshold: float) -> None:
        self._threshold = threshold
        self._blocked = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.observed_brightness: list[float] = []

    @overload
    def evaluate(
        self,
        context: FrameContext,
        *,
        is_short_circuited: Literal[False] = False,
    ) -> bool: ...

    @overload
    def evaluate(
        self,
        context: FrameContext,
        *,
        is_short_circuited: Literal[True],
    ) -> bool | None: ...

    def evaluate(
        self,
        context: FrameContext,
        *,
        is_short_circuited: bool = False,
    ) -> bool | None:
        if not self._blocked:
            self._blocked = True
            self.entered.set()
            if not self.release.wait(5):
                raise TimeoutError("test did not release blocked evaluation")
        brightness = float(np.mean(context.frame.image))
        self.observed_brightness.append(brightness)
        detected = brightness >= self._threshold
        return None if is_short_circuited else detected

    def reset(self) -> None:
        pass
