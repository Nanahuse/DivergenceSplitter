from __future__ import annotations

from divergencesplitter.frame.ndi import NdiReceiveError, NdiSupport
from divergencesplitter_ui.ndi_discovery import NdiDiscovery


def test_reports_support_and_sources() -> None:
    discovery = NdiDiscovery(
        support_probe=lambda: NdiSupport(True),
        source_lister=lambda timeout: ("Gaming PC (OBS)", "Laptop"),
    )

    discovery.refresh()
    discovery.join(2)

    assert discovery.support() == NdiSupport(True)
    assert discovery.sources() == ("Gaming PC (OBS)", "Laptop")


def test_unavailable_support_skips_listing() -> None:
    calls: list[int] = []
    discovery = NdiDiscovery(
        support_probe=lambda: NdiSupport(False, "no ndi"),
        source_lister=lambda timeout: calls.append(timeout) or (),
    )

    discovery.refresh()
    discovery.join(2)

    assert discovery.support() == NdiSupport(False, "no ndi")
    assert discovery.sources() == ()
    assert calls == []


def test_listing_failure_keeps_support() -> None:
    def fail(timeout: int) -> tuple[str, ...]:
        raise NdiReceiveError("discovery failed")

    discovery = NdiDiscovery(
        support_probe=lambda: NdiSupport(True),
        source_lister=fail,
    )

    discovery.refresh()
    discovery.join(2)

    assert discovery.support() == NdiSupport(True)
    assert discovery.sources() == ()


def test_support_is_none_before_refresh() -> None:
    discovery = NdiDiscovery()

    assert discovery.support() is None
    assert discovery.sources() == ()
