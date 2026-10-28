"""Opt-in checks against a live LiveSplit.Bridge JSON Protocol v4 instance.

Set ``DIVERGENCESPLITTER_BRIDGE_V4_PORT`` to a running Bridge (the official
LiveSplit.Bridge TestHost is suitable) to execute these tests. They are skipped
by default because the repository's CI does not run a Bridge process.
"""

from __future__ import annotations

import os
import threading
import time
from typing import cast

import pytest
from divergencesplitter import Action, LiveSplitConnection
from divergencesplitter_runtime.livesplit.adapter import (
    ActionExecution,
    LiveSplitBridgeAdapter,
    LiveSplitBridgeDiagnostics,
)
from divergencesplitter_runtime.livesplit.event_receiver import (
    BridgeEventConnectionLost,
    BridgeEventReceived,
    BridgeEventReceiver,
)
from divergencesplitter_runtime.livesplit.models import (
    LiveSplitResyncReason,
    LiveSplitSnapshot,
    TimerPhase,
    event_endpoint,
)
from livesplit_bridge import BridgeEventSubscriber, EventType

_PORT = os.environ.get("DIVERGENCESPLITTER_BRIDGE_V4_PORT")

pytestmark = pytest.mark.skipif(
    _PORT is None,
    reason="set DIVERGENCESPLITTER_BRIDGE_V4_PORT to run against a live v4 Bridge",
)


class _Diagnostics:
    def snapshot_mismatched(
        self,
        connection: LiveSplitConnection,
        action: Action,
        expected: LiveSplitSnapshot,
        actual: LiveSplitSnapshot,
    ) -> None: ...

    def action_precondition_failed(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None: ...

    def action_dispatched(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
        session_id: int | None,
        event_sequence: int | None,
        state_epoch: int,
    ) -> None: ...

    def action_succeeded(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None: ...

    def action_rejected(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
        code: str | None,
        message: str,
    ) -> None: ...

    def action_result_unknown(
        self,
        connection: LiveSplitConnection,
        action: Action,
        snapshot: LiveSplitSnapshot,
        error: Exception,
    ) -> None: ...

    def gap_detected(
        self,
        connection: LiveSplitConnection,
        baseline: LiveSplitSnapshot,
        received_session_id: int,
        received_event_sequence: int,
    ) -> None: ...


def _wait_for_event(
    adapter: LiveSplitBridgeAdapter,
    receiver: BridgeEventReceiver,
    target: EventType,
    *,
    timeout_seconds: float = 5,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        found = False
        # Apply every event in the batch before returning: a target event can
        # be followed by other authoritative events that the next Control
        # depends on.
        for message in receiver.drain():
            if isinstance(message, BridgeEventConnectionLost):
                pytest.fail(f"Bridge event connection was lost: {message.error}")
            assert isinstance(message, BridgeEventReceived)
            received = adapter.handle_event(message.event)
            if isinstance(received, LiveSplitResyncReason):
                pytest.fail(f"Bridge event stream lost integrity: {received}")
            if message.event.type is target:
                found = True
        if found:
            return
        time.sleep(0.01)
    pytest.fail(f"No {target} event arrived from the live v4 Bridge")


def _control(
    adapter: LiveSplitBridgeAdapter,
    receiver: BridgeEventReceiver,
    operation: str,
    target: EventType,
    expected_phase: TimerPhase,
    expected_index: int,
) -> None:
    snapshot = adapter.current_snapshot
    assert snapshot is not None
    outcome = adapter.execute_action(
        Action(operation),
        snapshot,
        adapter.state_epoch,
    )
    assert outcome.execution is ActionExecution.DISPATCHED
    _wait_for_event(adapter, receiver, target)
    current = adapter.current_snapshot
    assert current is not None
    assert current.phase is expected_phase
    assert current.split_index == expected_index


def test_live_v4_bridge_events_and_controls() -> None:
    assert _PORT is not None
    connection = LiveSplitConnection(int(_PORT))
    wakeup = threading.Event()
    receiver: BridgeEventReceiver = BridgeEventReceiver(
        subscriber_factory=lambda: BridgeEventSubscriber(
            event_endpoint(connection),
            receive_timeout_ms=50,
        ),
        wakeup=wakeup,
        receive_timeout_ms=50,
    )
    adapter = LiveSplitBridgeAdapter(
        connection,
        diagnostics=cast(LiveSplitBridgeDiagnostics, _Diagnostics()),
    )
    receiver.start()
    receiver.wait_until_started()
    try:
        initial = adapter.synchronize()
        assert initial.session_id > 0
        # The official TestHost exposes a two-segment Run. Requiring it keeps
        # Split, Undo, and Skip in the verified Control set.
        assert initial.snapshot.split_count >= 2
        assert initial.snapshot.phase in (
            TimerPhase.NOT_RUNNING,
            TimerPhase.RUNNING,
            TimerPhase.PAUSED,
            TimerPhase.ENDED,
        )

        if initial.snapshot.phase is not TimerPhase.NOT_RUNNING:
            _control(
                adapter,
                receiver,
                "reset",
                EventType.TIMER_RESET,
                TimerPhase.NOT_RUNNING,
                -1,
            )
        _control(
            adapter,
            receiver,
            "start",
            EventType.TIMER_STARTED,
            TimerPhase.RUNNING,
            0,
        )
        _control(
            adapter,
            receiver,
            "split",
            EventType.TIMER_SPLIT,
            TimerPhase.RUNNING,
            1,
        )
        _control(
            adapter,
            receiver,
            "undo",
            EventType.TIMER_UNDO,
            TimerPhase.RUNNING,
            0,
        )
        _control(
            adapter,
            receiver,
            "skip",
            EventType.TIMER_SKIPPED,
            TimerPhase.RUNNING,
            1,
        )
        _control(
            adapter,
            receiver,
            "pause",
            EventType.TIMER_PHASE_CHANGED,
            TimerPhase.PAUSED,
            adapter.current_snapshot.split_index if adapter.current_snapshot else 0,
        )
        _control(
            adapter,
            receiver,
            "resume",
            EventType.TIMER_PHASE_CHANGED,
            TimerPhase.RUNNING,
            adapter.current_snapshot.split_index if adapter.current_snapshot else 0,
        )
        _control(
            adapter,
            receiver,
            "reset",
            EventType.TIMER_RESET,
            TimerPhase.NOT_RUNNING,
            -1,
        )
    finally:
        adapter.close()
        receiver.stop()
