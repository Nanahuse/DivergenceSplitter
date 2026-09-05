"""Pure session control owning one non-daemon runtime thread.

The controller turns a confirmed configuration path into one runtime execution
and reports its terminal outcome. It reuses the shared configuration, scenario,
source, and runtime construction path; it only adds ownership, stop, and result
reporting. Dear PyGui and screen presentation live elsewhere in this package.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, TextIO

from divergencesplitter.frame.models import Frame
from divergencesplitter.frame.source import FrameSource
from divergencesplitter.scenario.models import Scenario
from divergencesplitter_runtime.application import (
    ApplicationDiagnostics,
    ApplicationRuntime,
    ApplicationStartupValidationError,
)
from divergencesplitter_runtime.configuration.json_file import (
    ConfigurationFileError,
    ConfigurationValidationError,
    load_configuration,
)
from divergencesplitter_runtime.configuration.models import (
    ApplicationConfiguration,
    SourceConfiguration,
)
from divergencesplitter_runtime.configuration.scenario_module import (
    ScenarioModuleExecutionError,
    ScenarioModuleValidationError,
    load_scenario_module,
)
from divergencesplitter_runtime.configuration.source_builder import (
    SourceConfigurationError,
    build_frame_source,
    resolve_configuration_path,
)
from divergencesplitter_runtime.diagnostics import OperationalDiagnostics
from divergencesplitter_runtime.metrics import RuntimeMetricsSnapshot
from divergencesplitter_runtime.observability import (
    ConditionObservation,
    DetectorTreeSnapshot,
)

_LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


class SessionState(Enum):
    """Lifecycle of one session owned by the controller."""

    IDLE = "IDLE"
    LOADING = "LOADING"
    CONNECTING = "CONNECTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class SessionFailureKind(Enum):
    """Boundary at which a session failed."""

    CONFIGURATION_FILE = "CONFIGURATION_FILE"
    CONFIGURATION_VALIDATION = "CONFIGURATION_VALIDATION"
    SCENARIO_EXECUTION = "SCENARIO_EXECUTION"
    SCENARIO_VALIDATION = "SCENARIO_VALIDATION"
    SOURCE_CONFIGURATION = "SOURCE_CONFIGURATION"
    STARTUP_VALIDATION = "STARTUP_VALIDATION"
    RUNTIME = "RUNTIME"


_TERMINAL_STATES = frozenset(
    {SessionState.COMPLETED, SessionState.FAILED, SessionState.STOPPED}
)


@dataclass(frozen=True)
class SessionResult:
    """Terminal outcome of one session."""

    state: SessionState
    error: BaseException | None = None
    failure_kind: SessionFailureKind | None = None


class SessionAlreadyActiveError(RuntimeError):
    """start() was called while a session is still in progress."""


class ConfigurationLoader(Protocol):
    def load(self, path: Path) -> ApplicationConfiguration: ...


class ScenarioLoader(Protocol):
    def load(self, path: Path) -> tuple[Scenario, ...]: ...


class SourceBuilder(Protocol):
    def build(
        self,
        configuration: SourceConfiguration,
        *,
        base_directory: Path,
    ) -> FrameSource: ...


class SessionDiagnostics(ApplicationDiagnostics, Protocol):
    def set_level(self, level: int) -> None: ...

    def bind_runtime(
        self,
        scenarios: tuple[Scenario, ...],
        frame_source: FrameSource,
    ) -> None: ...

    def is_runtime_started(self) -> bool: ...

    def configuration_failed(self, error: BaseException) -> None: ...

    def scenario_module_failed(self, error: BaseException) -> None: ...

    def startup_validation_failed(self, error: BaseException) -> None: ...

    def runtime_failed(self, error: BaseException) -> None: ...

    def completed(self) -> None: ...

    def take_latest_input_frame(self) -> Frame | None: ...

    def take_condition_observations(self) -> tuple[ConditionObservation, ...]: ...

    def detector_tree(self) -> DetectorTreeSnapshot | None: ...

    def metrics_snapshot(self) -> RuntimeMetricsSnapshot: ...


class DiagnosticsFactory(Protocol):
    def create(self) -> SessionDiagnostics: ...


class Runtime(Protocol):
    def run(self) -> None: ...

    def request_stop(self) -> None: ...


class RuntimeFactory(Protocol):
    def create(
        self,
        scenarios: tuple[Scenario, ...],
        frame_source: FrameSource,
        *,
        diagnostics: ApplicationDiagnostics,
    ) -> Runtime: ...


class DefaultConfigurationLoader:
    def load(self, path: Path) -> ApplicationConfiguration:
        return load_configuration(path)


class DefaultScenarioLoader:
    def load(self, path: Path) -> tuple[Scenario, ...]:
        return load_scenario_module(path)


class DefaultSourceBuilder:
    def build(
        self,
        configuration: SourceConfiguration,
        *,
        base_directory: Path,
    ) -> FrameSource:
        return build_frame_source(configuration, base_directory=base_directory)


class OperationalDiagnosticsFactory:
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def create(self) -> OperationalDiagnostics:
        return OperationalDiagnostics(self._stream)


class ApplicationRuntimeFactory:
    def create(
        self,
        scenarios: tuple[Scenario, ...],
        frame_source: FrameSource,
        *,
        diagnostics: ApplicationDiagnostics,
    ) -> Runtime:
        return ApplicationRuntime(scenarios, frame_source, diagnostics=diagnostics)


class SessionController:
    """Own one runtime execution and report its terminal outcome."""

    def __init__(
        self,
        *,
        configuration_loader: ConfigurationLoader,
        scenario_loader: ScenarioLoader,
        source_builder: SourceBuilder,
        runtime_factory: RuntimeFactory,
        diagnostics_factory: DiagnosticsFactory,
    ) -> None:
        self._configuration_loader = configuration_loader
        self._scenario_loader = scenario_loader
        self._source_builder = source_builder
        self._runtime_factory = runtime_factory
        self._diagnostics_factory = diagnostics_factory
        self._lock = threading.Lock()
        self._state = SessionState.IDLE
        self._result: SessionResult | None = None
        self._runtime: Runtime | None = None
        self._diagnostics: SessionDiagnostics | None = None
        self._stop_requested = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> SessionState:
        with self._lock:
            if (
                self._state is SessionState.CONNECTING
                and self._diagnostics is not None
                and self._diagnostics.is_runtime_started()
            ):
                self._state = (
                    SessionState.STOPPING
                    if self._stop_requested.is_set()
                    else SessionState.RUNNING
                )
            return self._state

    @property
    def result(self) -> SessionResult | None:
        with self._lock:
            return self._result

    @property
    def diagnostics(self) -> SessionDiagnostics | None:
        with self._lock:
            return self._diagnostics

    def start(self, configuration_path: str | Path) -> None:
        path = Path(configuration_path)
        with self._lock:
            if (
                self._state is not SessionState.IDLE
                and self._state not in _TERMINAL_STATES
            ):
                raise SessionAlreadyActiveError(
                    f"session is already {self._state.name}"
                )
            self._stop_requested.clear()
            self._state = SessionState.LOADING
            self._result = None
            self._runtime = None
            self._diagnostics = None
            self._thread = threading.Thread(
                target=self._run,
                args=(path,),
                name="session",
                daemon=False,
            )
            self._thread.start()

    def request_stop(self) -> None:
        with self._lock:
            if self._stop_requested.is_set():
                return
            self._stop_requested.set()
            runtime = self._runtime
            phase = self._state
            if runtime is not None and phase in {
                SessionState.CONNECTING,
                SessionState.RUNNING,
            }:
                self._state = SessionState.STOPPING
        if runtime is not None and phase in {
            SessionState.CONNECTING,
            SessionState.RUNNING,
        }:
            runtime.request_stop()

    def join(self, timeout: float | None = None) -> bool:
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def _run(self, path: Path) -> None:
        diagnostics: SessionDiagnostics | None = None
        try:
            diagnostics = self._diagnostics_factory.create()
            with self._lock:
                self._diagnostics = diagnostics
            if self._finish_if_stopped():
                return
            try:
                resolved_path = path.resolve()
            except OSError as error:
                diagnostics.configuration_failed(error)
                self._fail(SessionFailureKind.CONFIGURATION_FILE, error)
                return
            self._run_session(resolved_path, diagnostics)
        except BaseException as error:  # noqa: BLE001
            if diagnostics is not None:
                diagnostics.runtime_failed(error)
            self._fail(SessionFailureKind.RUNTIME, error)

    def _run_session(self, path: Path, diagnostics: SessionDiagnostics) -> None:
        try:
            configuration = self._configuration_loader.load(path)
        except ConfigurationFileError as error:
            diagnostics.configuration_failed(error.error)
            self._fail(SessionFailureKind.CONFIGURATION_FILE, error)
            return
        except ConfigurationValidationError as error:
            diagnostics.startup_validation_failed(error)
            self._fail(SessionFailureKind.CONFIGURATION_VALIDATION, error)
            return
        except BaseException as error:  # noqa: BLE001
            diagnostics.configuration_failed(error)
            self._fail(SessionFailureKind.CONFIGURATION_FILE, error)
            return

        if self._finish_if_stopped():
            return

        diagnostics.set_level(_LOG_LEVELS[configuration.runtime.log_level])
        scenario_path = resolve_configuration_path(
            configuration.scenario.script,
            base_directory=path.parent,
        )
        try:
            scenarios = self._scenario_loader.load(scenario_path)
        except ScenarioModuleExecutionError as error:
            diagnostics.scenario_module_failed(error.error)
            self._fail(SessionFailureKind.SCENARIO_EXECUTION, error)
            return
        except ScenarioModuleValidationError as error:
            diagnostics.startup_validation_failed(error)
            self._fail(SessionFailureKind.SCENARIO_VALIDATION, error)
            return
        except BaseException as error:  # noqa: BLE001
            diagnostics.scenario_module_failed(error)
            self._fail(SessionFailureKind.SCENARIO_EXECUTION, error)
            return

        if self._finish_if_stopped():
            return

        try:
            frame_source = self._source_builder.build(
                configuration.source,
                base_directory=path.parent,
            )
        except (SourceConfigurationError, ValueError) as error:
            diagnostics.startup_validation_failed(error)
            self._fail(SessionFailureKind.SOURCE_CONFIGURATION, error)
            return
        except BaseException as error:  # noqa: BLE001
            diagnostics.startup_validation_failed(error)
            self._fail(SessionFailureKind.SOURCE_CONFIGURATION, error)
            return

        if self._stop_requested.is_set():
            frame_source.close()
            self._finish(SessionState.STOPPED)
            return

        diagnostics.bind_runtime(scenarios, frame_source)
        try:
            runtime = self._runtime_factory.create(
                scenarios,
                frame_source,
                diagnostics=diagnostics,
            )
        except ExceptionGroup as error:
            frame_source.close()
            diagnostics.startup_validation_failed(error)
            self._fail(SessionFailureKind.STARTUP_VALIDATION, error)
            return
        except BaseException as error:  # noqa: BLE001
            frame_source.close()
            diagnostics.runtime_failed(error)
            self._fail(SessionFailureKind.RUNTIME, error)
            return

        with self._lock:
            self._runtime = runtime
            if self._stop_requested.is_set():
                stopped_before_run = True
            else:
                stopped_before_run = False
                self._state = SessionState.CONNECTING
        if stopped_before_run:
            frame_source.close()
            self._finish(SessionState.STOPPED)
            return

        try:
            runtime.run()
        except ApplicationStartupValidationError as error:
            diagnostics.startup_validation_failed(error.error)
            self._fail(SessionFailureKind.STARTUP_VALIDATION, error)
            return
        except BaseException as error:  # noqa: BLE001
            diagnostics.runtime_failed(error)
            self._fail(SessionFailureKind.RUNTIME, error)
            return

        if self._stop_requested.is_set():
            self._finish(SessionState.STOPPED)
        else:
            diagnostics.completed()
            self._finish(SessionState.COMPLETED)

    def _finish_if_stopped(self) -> bool:
        if not self._stop_requested.is_set():
            return False
        self._finish(SessionState.STOPPED)
        return True

    def _fail(self, kind: SessionFailureKind, error: BaseException) -> None:
        self._finish(SessionState.FAILED, error, kind)

    def _finish(
        self,
        state: SessionState,
        error: BaseException | None = None,
        failure_kind: SessionFailureKind | None = None,
    ) -> None:
        with self._lock:
            self._state = state
            self._result = SessionResult(state, error, failure_kind)
