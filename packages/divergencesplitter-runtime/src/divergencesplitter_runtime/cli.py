"""Command-line entry point for the DivergenceSplitter runtime."""

import argparse
import logging
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Never

from divergencesplitter_runtime.application import (
    ApplicationRuntime,
    ApplicationStartupValidationError,
)
from divergencesplitter_runtime.configuration.scenario_module import (
    ScenarioModuleExecutionError,
    ScenarioModuleValidationError,
    load_scenario_module,
)
from divergencesplitter_runtime.diagnostics import OperationalDiagnostics

EXIT_COMPLETED = 0
EXIT_USAGE_ERROR = 2
EXIT_SCENARIO_MODULE_ERROR = 3
EXIT_STARTUP_VALIDATION_ERROR = 4
EXIT_RUNTIME_ERROR = 5
EXIT_INTERRUPTED = 130

_LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}
_STATUS_INTERVAL_SECONDS = 1.0


class _StatusReporter:
    def __init__(
        self,
        diagnostics: OperationalDiagnostics,
        *,
        interval_seconds: float = _STATUS_INTERVAL_SECONDS,
    ) -> None:
        self._diagnostics = diagnostics
        self._interval_seconds = interval_seconds
        self._stop_requested = threading.Event()
        self._thread = threading.Thread(target=self._run, name="status-reporter")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_requested.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._stop_requested.wait(self._interval_seconds):
            snapshot = self._diagnostics.metrics_snapshot()
            self._diagnostics.runtime_fps(snapshot)


class _ArgumentParser(argparse.ArgumentParser):
    def __init__(self, diagnostics: OperationalDiagnostics, *, prog: str) -> None:
        super().__init__(prog=prog)
        self._diagnostics = diagnostics

    def error(self, message: str) -> Never:
        usage = " ".join(self.format_usage().split())
        self._diagnostics.usage_failed(f"{message}; {usage}")
        raise SystemExit(EXIT_USAGE_ERROR)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one trusted scenario module and return a process exit status."""

    diagnostics = OperationalDiagnostics(sys.stderr)
    parser = _ArgumentParser(diagnostics, prog="divergencesplitter")
    parser.add_argument(
        "--log-level",
        choices=tuple(_LOG_LEVELS),
        default="INFO",
    )
    parser.add_argument("scenario_module", type=Path)
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else EXIT_USAGE_ERROR

    diagnostics.set_level(_LOG_LEVELS[arguments.log_level])
    try:
        scenarios, frame_source = load_scenario_module(arguments.scenario_module)
    except KeyboardInterrupt:
        diagnostics.interrupted()
        return EXIT_INTERRUPTED
    except ScenarioModuleExecutionError as error:
        diagnostics.scenario_module_failed(error.error)
        return EXIT_SCENARIO_MODULE_ERROR
    except ScenarioModuleValidationError as error:
        diagnostics.startup_validation_failed(error)
        return EXIT_STARTUP_VALIDATION_ERROR

    diagnostics.bind_runtime(scenarios, frame_source)
    try:
        runtime = ApplicationRuntime(
            scenarios,
            frame_source,
            diagnostics=diagnostics,
        )
    except KeyboardInterrupt:
        diagnostics.interrupted()
        return EXIT_INTERRUPTED
    except ExceptionGroup as error:
        diagnostics.startup_validation_failed(error)
        return EXIT_STARTUP_VALIDATION_ERROR
    except Exception as error:  # noqa: BLE001
        diagnostics.runtime_failed(error)
        return EXIT_RUNTIME_ERROR

    reporter = _StatusReporter(diagnostics)
    reporter.start()
    try:
        runtime.run()
    except KeyboardInterrupt:
        runtime.request_stop()
        diagnostics.interrupted()
        return EXIT_INTERRUPTED
    except ApplicationStartupValidationError as error:
        diagnostics.startup_validation_failed(error.error)
        return EXIT_STARTUP_VALIDATION_ERROR
    except Exception as error:  # noqa: BLE001
        diagnostics.runtime_failed(error)
        return EXIT_RUNTIME_ERROR
    finally:
        reporter.stop()
    diagnostics.completed()
    return EXIT_COMPLETED
