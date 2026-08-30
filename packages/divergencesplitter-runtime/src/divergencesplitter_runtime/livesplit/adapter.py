"""Runtime boundary for the official LiveSplit.Bridge client."""

from typing import Self

from divergencesplitter import LiveSplitConnection
from livesplit_bridge import BridgeClient, BridgeEventSubscriber

from divergencesplitter_runtime.livesplit.mapping import (
    snapshot_from_proto,
    update_from_proto,
)
from divergencesplitter_runtime.livesplit.models import (
    LiveSplitSnapshot,
    LiveSplitUpdate,
)


class LiveSplitBridgeAdapter:
    def __init__(
        self,
        connection: LiveSplitConnection,
        *,
        client: BridgeClient | None = None,
        subscriber: BridgeEventSubscriber | None = None,
        rpc_timeout_ms: int = 3000,
        event_timeout_ms: int | None = None,
    ) -> None:
        owns_client = client is None
        self._client = (
            client
            if client is not None
            else BridgeClient(connection.rpc_endpoint, timeout_ms=rpc_timeout_ms)
        )
        try:
            self._subscriber = (
                subscriber
                if subscriber is not None
                else BridgeEventSubscriber(
                    connection.event_endpoint,
                    timeout_ms=event_timeout_ms,
                )
            )
        except Exception:
            if owns_client:
                self._client.close()
            raise
        self._closed = False

    def snapshot(self) -> LiveSplitSnapshot:
        return snapshot_from_proto(self._client.snapshot())

    def receive(self, *, timeout_ms: int | None = None) -> LiveSplitUpdate:
        return update_from_proto(self._subscriber.receive(timeout_ms=timeout_ms))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._subscriber.close()
        finally:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
