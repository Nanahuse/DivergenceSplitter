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
from divergencesplitter_runtime.configuration.app_settings_json import (
    default_app_settings_path,
    load_app_settings_or_default,
)
from divergencesplitter_runtime.configuration.models import Profile
from divergencesplitter_runtime.configuration.profile_json import (
    load_profile,
)
from divergencesplitter_runtime.configuration.reference_resize import (
    resize_scenario_references,
)
from divergencesplitter_runtime.configuration.scenario_loader import (
    ScenarioLoaderError,
    load_scenario,
)
from divergencesplitter_runtime.configuration.scenario_module import (
    ScenarioModuleExecutionError,
    ScenarioModuleValidationError,
)
from divergencesplitter_runtime.configuration.source_builder import (
    SourceConfigurationError,
    build_frame_source,
)
from divergencesplitter_runtime.configuration.strict_json import (
    ConfigurationFileError,
    ConfigurationValidationError,
)
from divergencesplitter_runtime.diagnostics import OperationalDiagnostics
from divergencesplitter_runtime.instances import ScenarioInstance

EXIT_COMPLETED = 0
EXIT_USAGE_ERROR = 2
EXIT_CONFIGURATION_LOAD_ERROR = 3
EXIT_STARTUP_VALIDATION_ERROR = 4
EXIT_RUNTIME_ERROR = 5
EXIT_INTERRUPTED = 130

_LOG_LEVELS = {
    "OFF": logging.CRITICAL + 1,
    "DEBUG": logging.DEBUG,
    "INFO": logging.DEBUG,
    "WARNING": logging.DEBUG,
    "ERROR": logging.DEBUG,
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


def _load_instances(
    profile: Profile,
) -> tuple[ScenarioInstance, ...]:
    return tuple(
        ScenarioInstance(
            connection=instance.connection,
            scenario=resize_scenario_references(
                load_scenario(instance.scenario),
                profile.source.transform,
            ),
        )
        for instance in profile.instances
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run one JSON profile and return a process exit status."""

    diagnostics = OperationalDiagnostics(sys.stderr)
    parser = _ArgumentParser(diagnostics, prog="divergencesplitter")
    parser.add_argument("profile", type=Path)
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else EXIT_USAGE_ERROR

    app_settings = load_app_settings_or_default(default_app_settings_path())
    profile_path = arguments.profile.resolve()
    try:
        profile = load_profile(profile_path)
    except ConfigurationFileError as error:
        diagnostics.configuration_failed(error.error)
        return EXIT_CONFIGURATION_LOAD_ERROR
    except ConfigurationValidationError as error:
        diagnostics.startup_validation_failed(error)
        return EXIT_STARTUP_VALIDATION_ERROR

    diagnostics.set_level(_LOG_LEVELS[app_settings.log_level])
    try:
        instances = _load_instances(profile)
    except KeyboardInterrupt:
        diagnostics.interrupted()
        return EXIT_INTERRUPTED
    except ScenarioModuleExecutionError as error:
        diagnostics.scenario_module_failed(error.error)
        return EXIT_CONFIGURATION_LOAD_ERROR
    except ScenarioModuleValidationError as error:
        diagnostics.startup_validation_failed(error)
        return EXIT_STARTUP_VALIDATION_ERROR
    except ScenarioLoaderError as error:
        diagnostics.scenario_module_failed(error.error)
        return EXIT_CONFIGURATION_LOAD_ERROR
    except ValueError as error:
        diagnostics.startup_validation_failed(error)
        return EXIT_STARTUP_VALIDATION_ERROR

    try:
        frame_source = build_frame_source(profile.source)
    except (SourceConfigurationError, ValueError) as error:
        diagnostics.startup_validation_failed(error)
        return EXIT_STARTUP_VALIDATION_ERROR

    diagnostics.bind_runtime(instances, frame_source)
    try:
        runtime = ApplicationRuntime(
            instances,
            frame_source,
            diagnostics=diagnostics,
            reaction_time_ms=app_settings.reaction_time_ms,
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
