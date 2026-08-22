from __future__ import annotations


class BridgeClientError(RuntimeError):
    """Base error for LiveSplit.Bridge client failures."""


class BridgeTransportError(BridgeClientError):
    """The ZeroMQ transport failed before a valid response was received."""


class BridgeTimeoutError(BridgeTransportError):
    """A Bridge RPC timed out and its result may be unknown."""

    def __init__(
        self,
        endpoint: str,
        timeout_ms: int,
        *,
        operation_may_have_completed: bool,
    ) -> None:
        self.endpoint = endpoint
        self.timeout_ms = timeout_ms
        self.operation_may_have_completed = operation_may_have_completed
        super().__init__(f"Bridge RPC timed out after {timeout_ms} ms ({endpoint})")


class BridgeProtocolError(BridgeClientError):
    """The Bridge returned data that violates protocol v1."""


class BridgeResponseError(BridgeClientError):
    """The Bridge returned a structured error response."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"Bridge error {code}: {message}")
