from __future__ import annotations

import threading
import time
from io import StringIO
from pathlib import Path

import pytest
from divergencesplitter import VideoFileSource
from divergencesplitter_runtime.application import ApplicationStartupValidationError
from divergencesplitter_runtime.configuration.json_file import (
    ConfigurationFileError,
    ConfigurationValidationError,
)
from divergencesplitter_runtime.configuration.models import (
    ApplicationConfiguration,
    RuntimeConfiguration,
    ScenarioConfiguration,
    VideoSourceConfiguration,
)
from divergencesplitter_runtime.configuration.scenario_module import (
    ScenarioModuleExecutionError,
    ScenarioModuleValidationError,
)
from divergencesplitter_runtime.configuration.source_builder import (
    SourceConfigurationError,
)
from divergencesplitter_runtime.diagnostics import OperationalDiagnostics
from divergencesplitter_ui.session import (
    SessionAlreadyActiveError,
    SessionController,
    SessionFailureKind,
    SessionResult,
    SessionState,
)


def make_configuration() -> ApplicationConfiguration:
    return ApplicationConfiguration(
        version=1,
        source=VideoSourceConfiguration("recording.mp4"),
        scenario=ScenarioConfiguration("./scenario.py"),
        runtime=RuntimeConfiguration("INFO"),
    )


class FakeConfigurationLoader:
    def __init__(
        self,
        *,
        configuration: ApplicationConfiguration | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._configuration = configuration or make_configuration()
        self._error = error
        self.loaded_paths: list[Path] = []

    def load(self, path: Path) -> ApplicationConfiguration:
        self.loaded_paths.append(path)
        if self._error is not None:
            raise self._error
        return self._configuration


class BlockingConfigurationLoader:
    def __init__(self, configuration: ApplicationConfiguration) -> None:
        self._configuration = configuration
        self.entered = threading.Event()
        self._release = threading.Event()

    def load(self, path: Path) -> ApplicationConfiguration:
        self.entered.set()
        self._release.wait()
        return self._configuration

    def release(self) -> None:
        self._release.set()


class FakeScenarioLoader:
    def __init__(
        self,
        *,
        scenarios: tuple = (),
        error: BaseException | None = None,
    ) -> None:
        self._scenarios = scenarios
        self._error = error
        self.loaded_paths: list[Path] = []

    def load(self, path: Path):
        self.loaded_paths.append(path)
        if self._error is not None:
            raise self._error
        return self._scenarios


class FakeSourceBuilder:
    def __init__(self, *, error: BaseException | None = None) -> None:
        self._error = error
        self.built: list = []

    def build(self, configuration, *, base_directory: Path):
        self.built.append((configuration, base_directory))
        if self._error is not None:
            raise self._error
        return VideoFileSource("recording.mp4")


class FakeDiagnostics(OperationalDiagnostics):
    def __init__(self) -> None:
        super().__init__(StringIO())
        self._started = threading.Event()
        self.set_level_calls: list[int] = []
        self.bind_runtime_calls: list = []
        self.runtime_started_calls = 0

    def set_level(self, level: int) -> None:
        self.set_level_calls.append(level)

    def bind_runtime(self, scenarios, frame_source) -> None:
        self.bind_runtime_calls.append((scenarios, frame_source))

    def runtime_started(self) -> None:
        self.runtime_started_calls += 1
        self._started.set()

    def is_runtime_started(self) -> bool:
        return self._started.is_set()


class FakeDiagnosticsFactory:
    def __init__(self) -> None:
        self.created: list[FakeDiagnostics] = []

    def create(self) -> FakeDiagnostics:
        diagnostics = FakeDiagnostics()
        self.created.append(diagnostics)
        return diagnostics


class FakeRuntime:
    def __init__(
        self,
        diagnostics,
        *,
        call_runtime_started: bool = True,
        error: BaseException | None = None,
        release_on_run: bool = True,
    ) -> None:
        self._diagnostics = diagnostics
        self._call_runtime_started = call_runtime_started
        self._error = error
        self._release_on_run = release_on_run
        self.ran = threading.Event()
        self._release = threading.Event()
        self.request_stop_calls = 0

    def request_stop(self) -> None:
        self.request_stop_calls += 1
        self._release.set()

    def release(self) -> None:
        self._release.set()

    def run(self) -> None:
        self.ran.set()
        if self._call_runtime_started:
            self._diagnostics.runtime_started()
        if not self._release_on_run:
            self._release.wait()
        if self._error is not None:
            raise self._error


class FakeRuntimeFactory:
    def __init__(self, *, release_on_run: bool = True) -> None:
        self.release_on_run = release_on_run
        self.runtimes: list[FakeRuntime] = []
        self.create_error: BaseException | None = None
        self.runtime_error: BaseException | None = None
        self.call_runtime_started = True

    def create(self, scenarios, frame_source, *, diagnostics) -> FakeRuntime:
        if self.create_error is not None:
            raise self.create_error
        runtime = FakeRuntime(
            diagnostics,
            call_runtime_started=self.call_runtime_started,
            error=self.runtime_error,
            release_on_run=self.release_on_run,
        )
        self.runtimes.append(runtime)
        return runtime


def make_controller(
    *,
    configuration_loader=None,
    scenario_loader=None,
    source_builder=None,
    runtime_factory=None,
    diagnostics_factory=None,
) -> tuple[SessionController, FakeRuntimeFactory, FakeDiagnosticsFactory]:
    runtime_factory = runtime_factory or FakeRuntimeFactory()
    diagnostics_factory = diagnostics_factory or FakeDiagnosticsFactory()
    controller = SessionController(
        configuration_loader=configuration_loader or FakeConfigurationLoader(),
        scenario_loader=scenario_loader or FakeScenarioLoader(),
        source_builder=source_builder or FakeSourceBuilder(),
        runtime_factory=runtime_factory,
        diagnostics_factory=diagnostics_factory,
    )
    return controller, runtime_factory, diagnostics_factory


def wait_until(predicate, *, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return False


class TestAutomaticStart:
    def test_valid_path_auto_starts_and_completes(self) -> None:
        controller, runtime_factory, diagnostics_factory = make_controller()

        assert controller.state is SessionState.IDLE
        controller.start(Path("config.json"))
        controller.join()

        assert controller.state is SessionState.COMPLETED
        assert controller.result is not None
        assert controller.result.state is SessionState.COMPLETED
        assert controller.result.error is None
        assert len(runtime_factory.runtimes) == 1
        assert runtime_factory.runtimes[0].ran.is_set()
        assert controller.diagnostics is diagnostics_factory.created[0]

    def test_start_returns_without_blocking_ui_thread(self) -> None:
        controller, _, _ = make_controller(
            runtime_factory=FakeRuntimeFactory(release_on_run=False),
        )

        controller.start(Path("config.json"))
        assert wait_until(lambda: controller.state is SessionState.RUNNING)

        controller.request_stop()
        assert wait_until(lambda: controller.state is SessionState.STOPPED)
        assert controller.join(1.0)


class TestDoubleStart:
    def test_start_while_active_is_rejected(self) -> None:
        controller, runtime_factory, _ = make_controller(
            runtime_factory=FakeRuntimeFactory(release_on_run=False),
        )

        controller.start(Path("config.json"))
        try:
            assert wait_until(lambda: controller.state is SessionState.RUNNING)
            with pytest.raises(SessionAlreadyActiveError):
                controller.start(Path("other.json"))
        finally:
            controller.request_stop()
            runtime_factory.runtimes[0].release()
            controller.join()


class TestStop:
    def test_stop_during_running_reaches_stopped(self) -> None:
        controller, runtime_factory, _ = make_controller(
            runtime_factory=FakeRuntimeFactory(release_on_run=False),
        )

        controller.start(Path("config.json"))
        assert wait_until(lambda: controller.state is SessionState.RUNNING)

        controller.request_stop()
        assert controller.state is SessionState.STOPPING
        assert runtime_factory.runtimes[0].request_stop_calls == 1

        runtime_factory.runtimes[0].release()
        controller.join()

        assert controller.state is SessionState.STOPPED
        assert controller.result is not None
        assert controller.result.state is SessionState.STOPPED

    def test_stop_during_loading_is_held_and_never_runs(self) -> None:
        loader = BlockingConfigurationLoader(make_configuration())
        controller, runtime_factory, _ = make_controller(configuration_loader=loader)

        controller.start(Path("config.json"))
        assert loader.entered.wait(5.0)
        assert controller.state is SessionState.LOADING

        controller.request_stop()
        loader.release()
        controller.join()

        assert controller.state is SessionState.STOPPED
        assert runtime_factory.runtimes == []

    def test_request_stop_is_idempotent(self) -> None:
        controller, runtime_factory, _ = make_controller(
            runtime_factory=FakeRuntimeFactory(release_on_run=False),
        )

        controller.start(Path("config.json"))
        try:
            assert wait_until(lambda: controller.state is SessionState.RUNNING)
            controller.request_stop()
            controller.request_stop()
        finally:
            runtime_factory.runtimes[0].release()
            controller.join()

        assert controller.state is SessionState.STOPPED
        assert runtime_factory.runtimes[0].request_stop_calls == 1


class TestFailureClassification:
    def test_unexpected_loader_failure_reaches_terminal_state(self) -> None:
        error = RuntimeError("unexpected loader failure")
        controller, _, _ = make_controller(
            configuration_loader=FakeConfigurationLoader(error=error),
        )

        controller.start(Path("config.json"))
        controller.join()

        assert controller.state is SessionState.FAILED
        assert controller.result == SessionResult(
            SessionState.FAILED,
            error,
            SessionFailureKind.CONFIGURATION_FILE,
        )

    @pytest.mark.parametrize(
        "error",
        [
            ConfigurationFileError(ValueError("unreadable")),
            ConfigurationValidationError("invalid schema"),
        ],
    )
    def test_configuration_failure(self, error) -> None:
        controller, _, _ = make_controller(
            configuration_loader=FakeConfigurationLoader(error=error),
        )

        controller.start(Path("config.json"))
        controller.join()

        assert controller.state is SessionState.FAILED
        assert controller.result is not None
        assert controller.result.error is error
        assert controller.result.failure_kind in {
            SessionFailureKind.CONFIGURATION_FILE,
            SessionFailureKind.CONFIGURATION_VALIDATION,
        }

    @pytest.mark.parametrize(
        "error",
        [
            ScenarioModuleExecutionError(ValueError("module failed")),
            ScenarioModuleValidationError("invalid exports", [ValueError("bad")]),
        ],
    )
    def test_scenario_failure(self, error) -> None:
        controller, _, _ = make_controller(
            scenario_loader=FakeScenarioLoader(error=error),
        )

        controller.start(Path("config.json"))
        controller.join()

        assert controller.state is SessionState.FAILED
        assert controller.result is not None
        assert controller.result.error is error
        assert controller.result.failure_kind in {
            SessionFailureKind.SCENARIO_EXECUTION,
            SessionFailureKind.SCENARIO_VALIDATION,
        }

    @pytest.mark.parametrize(
        "error",
        [
            SourceConfigurationError("unknown camera"),
            ValueError("invalid source"),
        ],
    )
    def test_source_failure(self, error) -> None:
        controller, _, _ = make_controller(
            source_builder=FakeSourceBuilder(error=error),
        )

        controller.start(Path("config.json"))
        controller.join()

        assert controller.state is SessionState.FAILED
        assert controller.result is not None
        assert controller.result.error is error
        assert controller.result.failure_kind is SessionFailureKind.SOURCE_CONFIGURATION

    def test_startup_validation_failure(self) -> None:
        runtime_factory = FakeRuntimeFactory(release_on_run=True)
        runtime_factory.call_runtime_started = False
        runtime_factory.runtime_error = ApplicationStartupValidationError(
            ValueError("split count mismatch")
        )
        controller, _, _ = make_controller(runtime_factory=runtime_factory)

        controller.start(Path("config.json"))
        controller.join()

        assert controller.state is SessionState.FAILED
        assert controller.result is not None
        assert isinstance(controller.result.error, ApplicationStartupValidationError)
        assert controller.result.failure_kind is SessionFailureKind.STARTUP_VALIDATION

    def test_runtime_failure(self) -> None:
        runtime_factory = FakeRuntimeFactory(release_on_run=True)
        runtime_factory.runtime_error = RuntimeError("runtime blew up")
        controller, _, _ = make_controller(runtime_factory=runtime_factory)

        controller.start(Path("config.json"))
        controller.join()

        assert controller.state is SessionState.FAILED
        assert controller.result is not None
        assert isinstance(controller.result.error, RuntimeError)
        assert controller.result.failure_kind is SessionFailureKind.RUNTIME


class TestRestart:
    def test_new_session_can_start_from_terminal_state(self) -> None:
        controller, runtime_factory, diagnostics_factory = make_controller()

        controller.start(Path("first.json"))
        controller.join()
        assert controller.state is SessionState.COMPLETED

        controller.start(Path("second.json"))
        controller.join()

        assert controller.state is SessionState.COMPLETED
        assert len(runtime_factory.runtimes) == 2
        assert len(diagnostics_factory.created) == 2
