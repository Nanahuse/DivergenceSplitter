from __future__ import annotations

from threading import get_ident
from types import TracebackType
from typing import Self

import zmq
from google.protobuf.message import DecodeError

from livesplit.bridge.v1 import bridge_pb2, common_pb2
from livesplit_bridge_client._mapping import (
    attach_result,
    bridge_event,
    operation_result,
    serialize,
    timer_operation_value,
    timer_snapshot,
)
from livesplit_bridge_client.errors import (
    BridgeClientError,
    BridgeProtocolError,
    BridgeResponseError,
    BridgeTimeoutError,
    BridgeTransportError,
)
from livesplit_bridge_client.models import (
    AttachResult,
    BridgeEvent,
    OperationResult,
    TimerOperation,
    TimerSnapshot,
)
from livesplit_bridge_client.schema import PROTOCOL_VERSION

DEFAULT_RPC_ENDPOINT = "tcp://127.0.0.1:54000"
DEFAULT_EVENT_ENDPOINT = "tcp://127.0.0.1:54001"
DEFAULT_TIMEOUT_MS = 3000


class LiveSplitBridgeClient:
    """Synchronous, single-owner-thread client for LiveSplit.Bridge v1."""

    def __init__(
        self,
        rpc_endpoint: str = DEFAULT_RPC_ENDPOINT,
        event_endpoint: str = DEFAULT_EVENT_ENDPOINT,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        if not rpc_endpoint:
            raise ValueError("rpc_endpoint must not be empty")
        if not event_endpoint:
            raise ValueError("event_endpoint must not be empty")
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int):
            raise TypeError("timeout_ms must be an integer")
        if timeout_ms < 0:
            raise ValueError("timeout_ms must be non-negative")
        self.rpc_endpoint = rpc_endpoint
        self.event_endpoint = event_endpoint
        self.timeout_ms = timeout_ms
        self._owner_thread = get_ident()
        self._context = zmq.Context()
        self._request_id = 0
        self._closed = False
        self._rpc_socket = self._new_rpc_socket()
        self._event_socket = self._new_event_socket()

    def _new_rpc_socket(self) -> zmq.Socket[bytes]:
        socket = self._context.socket(zmq.REQ)
        socket.setsockopt(zmq.LINGER, 0)
        socket.connect(self.rpc_endpoint)
        return socket

    def _new_event_socket(self) -> zmq.Socket[bytes]:
        socket = self._context.socket(zmq.SUB)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.SUBSCRIBE, b"")
        socket.connect(self.event_endpoint)
        return socket

    def _ensure_owner_thread(self) -> None:
        if get_ident() != self._owner_thread:
            raise BridgeClientError(
                "client sockets must be used from their owner thread"
            )

    def _ensure_usable(self) -> None:
        if self._closed:
            raise BridgeClientError("client is closed")
        self._ensure_owner_thread()

    def _reset_rpc_socket(self) -> None:
        self._rpc_socket.close(linger=0)
        if not self._closed:
            self._rpc_socket = self._new_rpc_socket()

    def _reset_event_socket(self) -> None:
        self._event_socket.close(linger=0)
        if not self._closed:
            self._event_socket = self._new_event_socket()

    def _request(
        self,
        request: bridge_pb2.Request,
        *,
        operation_may_have_completed: bool,
    ) -> bridge_pb2.Response:
        self._ensure_usable()
        self._request_id += 1
        request.protocol_version = PROTOCOL_VERSION
        request.request_id = self._request_id
        try:
            self._rpc_socket.send(serialize(request))
            if not self._rpc_socket.poll(self.timeout_ms, zmq.POLLIN):
                self._reset_rpc_socket()
                raise BridgeTimeoutError(
                    self.rpc_endpoint,
                    self.timeout_ms,
                    operation_may_have_completed=operation_may_have_completed,
                )
            response = bridge_pb2.Response.FromString(self._rpc_socket.recv())
        except BridgeTimeoutError:
            raise
        except (DecodeError, zmq.ZMQError) as error:
            self._reset_rpc_socket()
            if isinstance(error, DecodeError):
                raise BridgeProtocolError(
                    "Bridge returned malformed protobuf"
                ) from error
            raise BridgeTransportError(
                f"Bridge RPC transport failed: {error}"
            ) from error

        try:
            if response.protocol_version != PROTOCOL_VERSION:
                raise BridgeProtocolError(
                    f"Protocol version mismatch: expected {PROTOCOL_VERSION}, "
                    f"got {response.protocol_version}"
                )
            if response.request_id != request.request_id:
                raise BridgeProtocolError(
                    f"Request ID mismatch: expected {request.request_id}, "
                    f"got {response.request_id}"
                )
            if response.HasField("error"):
                raise BridgeResponseError(response.error.code, response.error.message)
            return response
        except BridgeProtocolError:
            self._reset_rpc_socket()
            raise

    def attach(self) -> AttachResult:
        response = self._request(
            bridge_pb2.Request(attach=bridge_pb2.AttachRequest()),
            operation_may_have_completed=False,
        )
        if response.WhichOneof("body") != "attach":
            self._reset_rpc_socket()
            raise BridgeProtocolError(
                "Attach request returned an unexpected response body"
            )
        try:
            return attach_result(response.attach)
        except BridgeProtocolError:
            self._reset_rpc_socket()
            raise

    def get_snapshot(self) -> TimerSnapshot:
        response = self._request(
            bridge_pb2.Request(get_snapshot=bridge_pb2.GetSnapshotRequest()),
            operation_may_have_completed=False,
        )
        if response.WhichOneof("body") != "get_snapshot":
            self._reset_rpc_socket()
            raise BridgeProtocolError(
                "Snapshot request returned an unexpected response body"
            )
        if not response.get_snapshot.HasField("snapshot"):
            self._reset_rpc_socket()
            raise BridgeProtocolError("Snapshot response has no snapshot")
        try:
            return timer_snapshot(response.get_snapshot.snapshot)
        except BridgeProtocolError:
            self._reset_rpc_socket()
            raise

    def execute_timer_operation(self, operation: TimerOperation) -> OperationResult:
        response = self._request(
            bridge_pb2.Request(
                timer_operation=bridge_pb2.TimerOperationRequest(
                    operation=timer_operation_value(operation)
                )
            ),
            operation_may_have_completed=True,
        )
        if response.WhichOneof("body") != "operation":
            self._reset_rpc_socket()
            raise BridgeProtocolError(
                "Timer operation returned an unexpected response body"
            )
        try:
            return operation_result(response.operation)
        except BridgeProtocolError:
            self._reset_rpc_socket()
            raise

    def poll_event(self, timeout_ms: int = 0) -> BridgeEvent | None:
        self._ensure_usable()
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int):
            raise TypeError("timeout_ms must be an integer")
        if timeout_ms < 0:
            raise ValueError("timeout_ms must be non-negative")
        try:
            if not self._event_socket.poll(timeout_ms, zmq.POLLIN):
                return None
            message = common_pb2.BridgeEvent.FromString(self._event_socket.recv())
            return bridge_event(message)
        except DecodeError as error:
            raise BridgeProtocolError("Bridge published malformed protobuf") from error
        except zmq.ZMQError as error:
            self._reset_event_socket()
            raise BridgeTransportError(
                f"Bridge event transport failed: {error}"
            ) from error

    def close(self) -> None:
        if self._closed:
            return
        self._ensure_owner_thread()
        self._closed = True
        self._rpc_socket.close(linger=0)
        self._event_socket.close(linger=0)
        self._context.term()

    def __enter__(self) -> Self:
        self._ensure_usable()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
