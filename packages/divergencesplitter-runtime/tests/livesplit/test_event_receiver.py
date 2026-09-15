"""Dedicated Bridge SUB event receiver transport contracts."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import cast

from divergencesplitter_runtime.livesplit.event_receiver import (
    BridgeEventConnectionLost,
    BridgeEventReceived,
    BridgeEventReceiver,
)
from livesplit_bridge import BridgeConnectionLostError, common_pb2


def make_event(sequence: int) -> common_pb2.BridgeEvent:
    return common_pb2.BridgeEvent(
        session_id=1,
        event_sequence=sequence,
        type=common_pb2.EVENT_STATE_SNAPSHOT,
        snapshot=common_pb2.TimerSnapshot(
            session_id=1,
            event_sequence=sequence,
            state_revision=sequence,
            run_revision=1,
            phase=common_pb2.RUNNING,
            split_index=0,
            split_count=1,
        ),
    )


class QueueSubscriber:
    """Blocking subscriber double delivering queued items in order."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._items: deque[object] = deque()
        self.created_on = threading.get_ident()
        self.closed = False

    def push(self, item: object) -> None:
        with self._condition:
            self._items.append(item)
            self._condition.notify_all()

    def receive(
        self, *, timeout_ms: int | None = None
    ) -> common_pb2.BridgeEvent | None:
        with self._condition:
            if not self._items:
                self._condition.wait(None if timeout_ms is None else timeout_ms / 1000)
            if not self._items:
                return None
            item = self._items.popleft()
        if isinstance(item, Exception):
            raise item
        return cast(common_pb2.BridgeEvent, item)

    def close(self) -> None:
        self.closed = True
        with self._condition:
            self._condition.notify_all()


def collect_events(
    receiver: BridgeEventReceiver,
    count: int,
    *,
    timeout_seconds: float = 2,
) -> tuple[BridgeEventReceived | BridgeEventConnectionLost, ...]:
    deadline = time.monotonic() + timeout_seconds
    collected: list[BridgeEventReceived | BridgeEventConnectionLost] = []
    while len(collected) < count and time.monotonic() < deadline:
        collected.extend(receiver.drain())
        time.sleep(0.001)
    return tuple(collected)


def test_receiver_delivers_events_in_receive_order() -> None:
    subscriber = QueueSubscriber()
    wakeup = threading.Event()
    receiver = BridgeEventReceiver(
        subscriber_factory=lambda: subscriber,
        wakeup=wakeup,
        receive_timeout_ms=1,
    )
    receiver.start()
    receiver.wait_until_started()
    try:
        for sequence in (10, 11, 12):
            subscriber.push(make_event(sequence))

        messages = collect_events(receiver, 3)
        sequences = [
            message.event.event_sequence
            for message in messages
            if isinstance(message, BridgeEventReceived)
        ]
        assert sequences == [10, 11, 12]
    finally:
        receiver.stop()


def test_receiver_creates_subscriber_on_its_own_thread() -> None:
    created_on: list[int] = []
    subscriber = QueueSubscriber()

    def factory() -> QueueSubscriber:
        created_on.append(threading.get_ident())
        return subscriber

    receiver = BridgeEventReceiver(
        subscriber_factory=factory,
        wakeup=threading.Event(),
        receive_timeout_ms=1,
    )
    receiver.start()
    receiver.wait_until_started()
    try:
        assert created_on
        assert created_on[0] != threading.get_ident()
    finally:
        receiver.stop()


def test_receiver_reports_connection_loss_and_stops() -> None:
    subscriber = QueueSubscriber()
    wakeup = threading.Event()
    receiver = BridgeEventReceiver(
        subscriber_factory=lambda: subscriber,
        wakeup=wakeup,
        receive_timeout_ms=1,
    )
    receiver.start()
    receiver.wait_until_started()
    try:
        subscriber.push(BridgeConnectionLostError("heartbeats missing"))

        messages = collect_events(receiver, 1)
        assert len(messages) == 1
        assert isinstance(messages[0], BridgeEventConnectionLost)
        assert isinstance(messages[0].error, BridgeConnectionLostError)
    finally:
        receiver.stop()


def test_receiver_overflow_is_reported_without_silent_drop() -> None:
    subscriber = QueueSubscriber()
    wakeup = threading.Event()
    receiver = BridgeEventReceiver(
        subscriber_factory=lambda: subscriber,
        wakeup=wakeup,
        receive_timeout_ms=1,
        capacity=1,
    )
    receiver.start()
    receiver.wait_until_started()
    try:
        for sequence in (1, 2, 3):
            subscriber.push(make_event(sequence))

        messages = collect_events(receiver, 1)
        assert len(messages) == 1
        assert receiver.take_overflow() is True
    finally:
        receiver.stop()


def test_receiver_stop_joins_thread_and_closes_subscriber() -> None:
    subscriber = QueueSubscriber()
    receiver = BridgeEventReceiver(
        subscriber_factory=lambda: subscriber,
        wakeup=threading.Event(),
        receive_timeout_ms=1,
    )
    receiver.start()
    receiver.wait_until_started()

    receiver.stop()

    assert subscriber.closed
    threads = [
        thread
        for thread in threading.enumerate()
        if thread.name == "bridge-event-receiver"
    ]
    assert threads == []
