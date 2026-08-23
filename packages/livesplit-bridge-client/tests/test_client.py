from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
import zmq
from livesplit.bridge.v1 import bridge_pb2, common_pb2

from livesplit_bridge_client import (
    BridgeClientError,
    BridgeEventType,
    BridgeProtocolError,
    BridgeResponseError,
    BridgeTimeoutError,
    LiveSplitBridgeClient,
    TimerOperation,
    TimerPhase,
)


def unused_tcp_endpoint() -> str:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{listener.getsockname()[1]}"


def proto_snapshot(*, sequence: int = 4) -> common_pb2.TimerSnapshot:
    return common_pb2.TimerSnapshot(
        state_revision=2,
        session_id=3,
        event_sequence=sequence,
        phase=common_pb2.RUNNING,
        split_index=0,
        split_count=2,
    )


@contextmanager
def rpc_server(
    handlers: list[Callable[[bridge_pb2.Request], bridge_pb2.Response]],
) -> Iterator[str]:
    endpoint = unused_tcp_endpoint()
    ready = threading.Event()
    failures: list[BaseException] = []

    def run() -> None:
        context = zmq.Context()
        responder = context.socket(zmq.REP)
        responder.setsockopt(zmq.LINGER, 0)
        try:
            responder.bind(endpoint)
            ready.set()
            for handler in handlers:
                request = bridge_pb2.Request.FromString(responder.recv())
                responder.send(handler(request).SerializeToString())
        except BaseException as error:  # noqa: BLE001
            failures.append(error)
        finally:
            responder.close(linger=0)
            context.term()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(1)
    try:
        yield endpoint
    finally:
        thread.join(2)
        assert not thread.is_alive()
        assert not failures


def response_for(
    request: bridge_pb2.Request,
    body: (
        bridge_pb2.AttachResponse
        | bridge_pb2.GetSnapshotResponse
        | common_pb2.OperationResponse
        | common_pb2.BridgeError
    ),
) -> bridge_pb2.Response:
    response = bridge_pb2.Response(
        protocol_version=1,
        request_id=request.request_id,
    )
    if isinstance(body, bridge_pb2.AttachResponse):
        response.attach.CopyFrom(body)
    elif isinstance(body, bridge_pb2.GetSnapshotResponse):
        response.get_snapshot.CopyFrom(body)
    elif isinstance(body, common_pb2.OperationResponse):
        response.operation.CopyFrom(body)
    else:
        response.error.CopyFrom(body)
    return response


def test_attach_snapshot_and_operation_are_typed() -> None:
    def attach(request: bridge_pb2.Request) -> bridge_pb2.Response:
        return response_for(
            request,
            bridge_pb2.AttachResponse(
                session_id=3,
                snapshot=proto_snapshot(),
            ),
        )

    def snapshot(request: bridge_pb2.Request) -> bridge_pb2.Response:
        return response_for(
            request,
            bridge_pb2.GetSnapshotResponse(snapshot=proto_snapshot()),
        )

    def operation(request: bridge_pb2.Request) -> bridge_pb2.Response:
        assert request.timer_operation.operation == common_pb2.TIMER_SPLIT
        return response_for(
            request,
            common_pb2.OperationResponse(
                success=True,
                message="OK",
                snapshot=proto_snapshot(),
            ),
        )

    with rpc_server([attach, snapshot, operation]) as endpoint:
        with LiveSplitBridgeClient(
            rpc_endpoint=endpoint,
            event_endpoint=unused_tcp_endpoint(),
        ) as client:
            assert client.attach().session_id == 3
            assert client.get_snapshot().phase is TimerPhase.RUNNING
            assert client.execute_timer_operation(TimerOperation.SPLIT).success


def test_bridge_error_is_structured() -> None:
    def error(request: bridge_pb2.Request) -> bridge_pb2.Response:
        return response_for(
            request,
            common_pb2.BridgeError(code=100, message="bad version"),
        )

    with rpc_server([error]) as endpoint:
        with LiveSplitBridgeClient(
            rpc_endpoint=endpoint,
            event_endpoint=unused_tcp_endpoint(),
        ) as client:
            with pytest.raises(BridgeResponseError) as raised:
                client.get_snapshot()
    assert raised.value.code == 100


def test_request_id_mismatch_is_rejected() -> None:
    def mismatch(request: bridge_pb2.Request) -> bridge_pb2.Response:
        return bridge_pb2.Response(
            protocol_version=1,
            request_id=request.request_id + 1,
            get_snapshot=bridge_pb2.GetSnapshotResponse(snapshot=proto_snapshot()),
        )

    with rpc_server([mismatch]) as endpoint:
        with LiveSplitBridgeClient(
            rpc_endpoint=endpoint,
            event_endpoint=unused_tcp_endpoint(),
        ) as client:
            with pytest.raises(BridgeProtocolError, match="Request ID"):
                client.get_snapshot()


def test_protocol_version_mismatch_is_rejected() -> None:
    def mismatch(request: bridge_pb2.Request) -> bridge_pb2.Response:
        return bridge_pb2.Response(
            protocol_version=2,
            request_id=request.request_id,
            get_snapshot=bridge_pb2.GetSnapshotResponse(snapshot=proto_snapshot()),
        )

    with rpc_server([mismatch]) as endpoint:
        with LiveSplitBridgeClient(
            rpc_endpoint=endpoint,
            event_endpoint=unused_tcp_endpoint(),
        ) as client:
            with pytest.raises(BridgeProtocolError, match="Protocol version"):
                client.get_snapshot()


def test_timeout_recreates_req_socket_without_retrying() -> None:
    endpoint = unused_tcp_endpoint()
    ready = threading.Event()
    received: list[int] = []

    def run() -> None:
        context = zmq.Context()
        responder = context.socket(zmq.REP)
        responder.setsockopt(zmq.LINGER, 0)
        responder.bind(endpoint)
        ready.set()
        first = bridge_pb2.Request.FromString(responder.recv())
        received.append(first.request_id)
        time.sleep(0.1)
        responder.send(
            response_for(
                first,
                common_pb2.OperationResponse(
                    success=True,
                    message="OK",
                    snapshot=proto_snapshot(),
                ),
            ).SerializeToString()
        )
        second = bridge_pb2.Request.FromString(responder.recv())
        received.append(second.request_id)
        responder.send(
            response_for(
                second,
                bridge_pb2.GetSnapshotResponse(snapshot=proto_snapshot()),
            ).SerializeToString()
        )
        responder.close(linger=0)
        context.term()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(1)
    with LiveSplitBridgeClient(
        rpc_endpoint=endpoint,
        event_endpoint=unused_tcp_endpoint(),
        timeout_ms=30,
    ) as client:
        with pytest.raises(BridgeTimeoutError) as raised:
            client.execute_timer_operation(TimerOperation.SPLIT)
        assert raised.value.operation_may_have_completed
        time.sleep(0.12)
        assert client.get_snapshot().session_id == 3
    thread.join(2)
    assert received == [1, 2]


def test_poll_event_is_typed_and_times_out() -> None:
    rpc_endpoint = unused_tcp_endpoint()
    event_endpoint = unused_tcp_endpoint()
    context = zmq.Context()
    publisher = context.socket(zmq.PUB)
    publisher.setsockopt(zmq.LINGER, 0)
    publisher.bind(event_endpoint)
    try:
        with LiveSplitBridgeClient(
            rpc_endpoint=rpc_endpoint,
            event_endpoint=event_endpoint,
        ) as client:
            assert client.poll_event(timeout_ms=0) is None
            time.sleep(0.1)
            publisher.send(
                common_pb2.BridgeEvent(
                    session_id=3,
                    event_sequence=5,
                    type=common_pb2.EVENT_TIMER_SPLIT,
                    snapshot=proto_snapshot(sequence=5),
                    description="split",
                ).SerializeToString()
            )
            event = client.poll_event(timeout_ms=500)
            assert event is not None
            assert event.type is BridgeEventType.TIMER_SPLIT
    finally:
        publisher.close(linger=0)
        context.term()


def test_close_is_idempotent() -> None:
    client = LiveSplitBridgeClient(
        rpc_endpoint=unused_tcp_endpoint(),
        event_endpoint=unused_tcp_endpoint(),
    )
    client.close()
    client.close()


def test_close_rejects_foreign_thread() -> None:
    client = LiveSplitBridgeClient(
        rpc_endpoint=unused_tcp_endpoint(),
        event_endpoint=unused_tcp_endpoint(),
    )
    errors: list[BaseException] = []

    def close_from_foreign_thread() -> None:
        try:
            client.close()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=close_from_foreign_thread)
    thread.start()
    thread.join(1)

    assert len(errors) == 1
    assert isinstance(errors[0], BridgeClientError)
    client.close()
