"""LiveSplit connection data model."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LiveSplitConnection:
    rpc_endpoint: str
    event_endpoint: str
