"""Typed public API for LiveSplit.Bridge."""

from livesplit_bridge_client.client import (
    DEFAULT_EVENT_ENDPOINT,
    DEFAULT_RPC_ENDPOINT,
    DEFAULT_TIMEOUT_MS,
    LiveSplitBridgeClient,
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
    BridgeEventType,
    OperationResult,
    TimerOperation,
    TimerPhase,
    TimerSnapshot,
)
from livesplit_bridge_client.schema import BRIDGE_SCHEMA_COMMIT, PROTOCOL_VERSION

__all__ = [
    "BRIDGE_SCHEMA_COMMIT",
    "DEFAULT_EVENT_ENDPOINT",
    "DEFAULT_RPC_ENDPOINT",
    "DEFAULT_TIMEOUT_MS",
    "PROTOCOL_VERSION",
    "AttachResult",
    "BridgeClientError",
    "BridgeEvent",
    "BridgeEventType",
    "BridgeProtocolError",
    "BridgeResponseError",
    "BridgeTimeoutError",
    "BridgeTransportError",
    "LiveSplitBridgeClient",
    "OperationResult",
    "TimerOperation",
    "TimerPhase",
    "TimerSnapshot",
]
