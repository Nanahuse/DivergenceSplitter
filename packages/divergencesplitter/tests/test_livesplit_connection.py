import pytest
from divergencesplitter import LiveSplitConnection


@pytest.mark.parametrize(
    ("host", "port", "authority"),
    [
        ("127.0.0.1", 54000, "127.0.0.1:54000"),
        ("timer.local", 54100, "timer.local:54100"),
        ("::1", 54000, "[::1]:54000"),
    ],
)
def test_endpoints_share_host_and_port(host: str, port: int, authority: str) -> None:
    connection = LiveSplitConnection(host, port)
    assert connection.rpc_endpoint == f"ws://{authority}/bridge/v1/rpc"
    assert connection.event_endpoint == f"ws://{authority}/bridge/v1/events"


@pytest.mark.parametrize(
    "host",
    [
        "",
        " ",
        "local host",
        "ws://localhost",
        "localhost:54000",
        "host/path",
        "user@host",
        "host?query",
        "host#fragment",
    ],
)
def test_rejects_host_with_url_components(host: str) -> None:
    with pytest.raises(ValueError, match="host"):
        LiveSplitConnection(host, 54000)


@pytest.mark.parametrize("port", [0, -1, 65536, True, 54000.5, "54000"])
def test_rejects_invalid_port(port) -> None:
    with pytest.raises(ValueError, match="port"):
        LiveSplitConnection("localhost", port)
