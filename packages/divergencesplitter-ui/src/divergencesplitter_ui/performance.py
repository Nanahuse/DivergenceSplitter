"""Lightweight performance instrumentation for the Flet UI hot paths.

This module measures how long the Flet UI spends in the work it owns: reading
Monitor snapshots, building presentation models, repainting the page, and
preparing/rendering the input preview. It deliberately keeps the runtime
untouched; the runtime already publishes its own throughput and latency metrics.

Samples are aggregated in memory per section and flushed about once per second
as ``ui.performance`` DEBUG records, so a hot path never formats a string or
touches a handler per tick. The logger stays disabled unless its level admits
DEBUG, which follows the session's existing ``OFF``/``DEBUG`` choice, so normal
runs pay only an ``isEnabledFor`` check.

Three development-only environment switches isolate a single section without
changing the production configuration surface:

* ``DIVERGENCESPLITTER_PERF_DISABLE_PREVIEW``
* ``DIVERGENCESPLITTER_PERF_DISABLE_PAGE_UPDATE``
* ``DIVERGENCESPLITTER_PERF_DISABLE_DIAGNOSTICS``

They are read once at import; normally unset, they leave the UI unchanged.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

LOGGER_NAME = "divergencesplitter.ui.performance"
EVENT_NAME = "ui.performance"
DEFAULT_FLUSH_INTERVAL_NS = 1_000_000_000
_DISABLED_LEVEL = logging.CRITICAL + 1

MONITOR_SNAPSHOT = "monitor.snapshot"
MONITOR_APPLY = "monitor.apply"
SCENARIO_OVERVIEW_PRESENTATION = "monitor.scenario_overview.presentation"
DIAGNOSTICS_PRESENTATION = "monitor.diagnostics.presentation"
FLET_PAGE_UPDATE = "flet.page_update"
PREVIEW_PREPARE = "preview.prepare"
PREVIEW_RAW_IMAGE_RENDER = "preview.raw_image_render"

_ENVIRONMENT_NAMES = {
    "disable_input_preview": "DIVERGENCESPLITTER_PERF_DISABLE_PREVIEW",
    "disable_page_update": "DIVERGENCESPLITTER_PERF_DISABLE_PAGE_UPDATE",
    "disable_diagnostics": "DIVERGENCESPLITTER_PERF_DISABLE_DIAGNOSTICS",
}

_BUILTIN_LOG_RECORD_FIELDS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "event_name"}


class _StructuredFormatter(logging.Formatter):
    """Mirror the runtime's one-line ``event_name key=value`` format."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = (
            datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        event_name = getattr(record, "event_name", record.getMessage())
        fields = [
            f"{key}={_format_value(value)}"
            for key, value in record.__dict__.items()
            if key not in _BUILTIN_LOG_RECORD_FIELDS
        ]
        suffix = "" if not fields else f" {' '.join(fields)}"
        return (
            f"{timestamp} {record.levelname} [{record.threadName}] {event_name}{suffix}"
        )


class _SafeStreamHandler(logging.StreamHandler):
    """Write to a stream that may be missing or closing without raising."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            stream = self.stream
            stream.write(message + self.terminator)
            self.flush()
        except Exception:  # noqa: BLE001
            return


@dataclass(frozen=True)
class SectionStats:
    """Aggregated timing for one section over the current flush window."""

    count: int
    total_ns: int
    max_ns: int

    @property
    def average_ns(self) -> int:
        """Mean elapsed nanoseconds, or ``0`` when nothing was sampled."""

        return 0 if self.count == 0 else self.total_ns // self.count


class _SectionSamples:
    """Mutable accumulator for one section; bounded to a few integers."""

    __slots__ = ("count", "max_ns", "total_ns")

    def __init__(self) -> None:
        self.count = 0
        self.total_ns = 0
        self.max_ns = 0

    def record(self, elapsed_ns: int) -> None:
        self.count += 1
        self.total_ns += elapsed_ns
        self.max_ns = max(self.max_ns, elapsed_ns)

    def stats(self) -> SectionStats:
        return SectionStats(self.count, self.total_ns, self.max_ns)


class PerformanceMetrics:
    """Aggregate per-section durations and flush them as DEBUG records.

    Recording is a no-op while DEBUG is disabled, so an idle run only pays an
    ``isEnabledFor`` check per sample. The flush window resets on every flush,
    including an empty one, so reported samples describe only the last interval.
    """

    def __init__(
        self,
        *,
        interval_ns: int = DEFAULT_FLUSH_INTERVAL_NS,
        clock: Callable[[], int] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._interval_ns = interval_ns
        self._clock = time.perf_counter_ns if clock is None else clock
        self._logger = logging.getLogger(LOGGER_NAME) if logger is None else logger
        self._samples: dict[str, _SectionSamples] = {}
        self._last_flush_ns: int | None = None

    @property
    def enabled(self) -> bool:
        """Whether the backing logger currently accepts DEBUG records."""

        return self._logger.isEnabledFor(logging.DEBUG)

    def record(self, section: str, elapsed_ns: int) -> None:
        """Accumulate one measured duration under ``section``."""

        if not self.enabled:
            return
        sample = self._samples.get(section)
        if sample is None:
            sample = _SectionSamples()
            self._samples[section] = sample
        sample.record(elapsed_ns)

    @contextmanager
    def measure(self, section: str) -> Iterator[None]:
        """Time the enclosed block and record it; cheap when DEBUG is off."""

        if not self.enabled:
            yield
            return
        started_at = self._clock()
        try:
            yield
        finally:
            self.record(section, self._clock() - started_at)

    def snapshot(self) -> Mapping[str, SectionStats]:
        """Return the current window's aggregates without flushing them."""

        return {section: sample.stats() for section, sample in self._samples.items()}

    def reset(self) -> None:
        """Drop every accumulated sample."""

        self._samples = {}

    def flush_if_due(self, now_ns: int | None = None) -> None:
        """Emit and reset the window once the flush interval has elapsed."""

        if not self.enabled:
            return
        now = self._clock() if now_ns is None else now_ns
        if (
            self._last_flush_ns is not None
            and now - self._last_flush_ns < self._interval_ns
        ):
            return
        self._flush(now)

    def _flush(self, now_ns: int) -> None:
        samples, self._samples = self._samples, {}
        self._last_flush_ns = now_ns
        for section in sorted(samples):
            stats = samples[section].stats()
            self._logger.log(
                logging.DEBUG,
                EVENT_NAME,
                extra={
                    "event_name": EVENT_NAME,
                    "section": section,
                    "count": stats.count,
                    "avg_ms": round(stats.average_ns / 1_000_000, 2),
                    "max_ms": round(stats.max_ns / 1_000_000, 2),
                },
            )


@dataclass(frozen=True)
class PerformanceFlags:
    """Development-only section switches; all default to the normal UI."""

    disable_input_preview: bool = False
    disable_page_update: bool = False
    disable_diagnostics: bool = False

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> PerformanceFlags:
        """Read the ``DIVERGENCESPLITTER_PERF_DISABLE_*`` switches."""

        source = os.environ if environ is None else environ
        return cls(
            disable_input_preview=_environment_flag(
                source, _ENVIRONMENT_NAMES["disable_input_preview"]
            ),
            disable_page_update=_environment_flag(
                source, _ENVIRONMENT_NAMES["disable_page_update"]
            ),
            disable_diagnostics=_environment_flag(
                source, _ENVIRONMENT_NAMES["disable_diagnostics"]
            ),
        )


def _environment_flag(environ: Mapping[str, str], name: str) -> bool:
    value = environ.get(name)
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def _format_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)


FLAGS = PerformanceFlags.from_environment()
METRICS = PerformanceMetrics()

_handler_configured = False


def configure_performance_logging(
    *,
    log_path: Path | None = None,
    stream: TextIO | None = None,
) -> None:
    """Attach the performance handler once, disabled until the level is raised.

    ``log_path`` mirrors the runtime's rotating file behavior and is used by the
    desktop entry point; ``stream`` is the fallback for console runs. Only the
    first call installs a handler, so repeated construction stays idempotent.
    """

    global _handler_configured
    logger = logging.getLogger(LOGGER_NAME)
    logger.propagate = False
    if logger.level == logging.NOTSET:
        logger.setLevel(_DISABLED_LEVEL)
    if _handler_configured:
        return
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
            delay=True,
        )
    elif stream is not None:
        handler = _SafeStreamHandler(stream)
    else:
        return
    handler.setFormatter(_StructuredFormatter())
    logger.addHandler(handler)
    _handler_configured = True


def set_performance_level(level: int) -> None:
    """Follow the session log level so performance logs stay DEBUG-only."""

    logging.getLogger(LOGGER_NAME).setLevel(level)
