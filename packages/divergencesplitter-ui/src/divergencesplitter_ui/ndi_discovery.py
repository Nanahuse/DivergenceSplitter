"""Background NDI capability probing and source discovery for the UI.

The Dear PyGui render thread must never block on NDI, so capability probing and
source listing run on a short-lived worker thread. The page requests a refresh
and reads the most recent result on its next tick.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from divergencesplitter.frame.ndi import (
    NdiError,
    NdiSupport,
    detect_ndi_support,
    discover_ndi_sources,
)

DEFAULT_DISCOVERY_TIMEOUT_MS = 1000


class NdiDiscovery:
    """Probe NDI capability and list sources without blocking the caller."""

    def __init__(
        self,
        *,
        support_probe: Callable[[], NdiSupport] = detect_ndi_support,
        source_lister: Callable[[int], tuple[str, ...]] = discover_ndi_sources,
        timeout_ms: int = DEFAULT_DISCOVERY_TIMEOUT_MS,
    ) -> None:
        self._support_probe = support_probe
        self._source_lister = source_lister
        self._timeout_ms = timeout_ms
        self._lock = threading.Lock()
        self._support: NdiSupport | None = None
        self._sources: tuple[str, ...] = ()
        self._refresh_requested = False
        self._thread: threading.Thread | None = None

    def refresh(self) -> None:
        """Request a refresh, starting the worker if it is not already running."""

        with self._lock:
            self._refresh_requested = True
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run, name="ndi-discovery", daemon=True
            )
            self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def support(self) -> NdiSupport | None:
        with self._lock:
            return self._support

    def sources(self) -> tuple[str, ...]:
        with self._lock:
            return self._sources

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._refresh_requested:
                    return
                self._refresh_requested = False
            support = self._support_probe()
            sources: tuple[str, ...] = ()
            if support.available:
                try:
                    sources = self._source_lister(self._timeout_ms)
                except NdiError:
                    sources = ()
            with self._lock:
                self._support = support
                self._sources = sources
