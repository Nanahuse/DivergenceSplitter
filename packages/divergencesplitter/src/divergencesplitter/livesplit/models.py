"""LiveSplit connection data model."""

from dataclasses import dataclass
from ipaddress import IPv6Address


@dataclass(frozen=True)
class LiveSplitConnection:
    host: str = "127.0.0.1"
    port: int = 54000

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip():
            raise ValueError("host must not be empty")
        host = self.host
        if any(character.isspace() for character in host) or any(
            character in host for character in "/\\@?#[]"
        ):
            raise ValueError(
                "host must be a hostname or IP address, without a URL or port"
            )
        if ":" in host:
            try:
                IPv6Address(host)
            except ValueError:
                raise ValueError(
                    "host must be a hostname or IP address, without a URL or port"
                ) from None
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("port must be an integer between 1 and 65535")

    @property
    def rpc_endpoint(self) -> str:
        return f"{self._base_url}/bridge/v1/rpc"

    @property
    def event_endpoint(self) -> str:
        return f"{self._base_url}/bridge/v1/events"

    @property
    def _base_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"ws://{host}:{self.port}"
