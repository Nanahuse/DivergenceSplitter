"""LiveSplit connection data model."""

from dataclasses import dataclass

MIN_PORT = 1
MAX_PORT = 65535


@dataclass(frozen=True)
class LiveSplitConnection:
    """The LiveSplit.Bridge WebSocket port one scenario connects to.

    Only the port is persisted; the runtime derives the protocol-specific RPC
    and Events endpoint paths from it. Host is fixed to the loopback interface
    and is deliberately not part of the configuration.
    """

    port: int

    def __post_init__(self) -> None:
        if type(self.port) is not int:
            raise TypeError("port must be an integer")
        if not MIN_PORT <= self.port <= MAX_PORT:
            raise ValueError(
                f"port must be between {MIN_PORT} and {MAX_PORT}: {self.port!r}"
            )
