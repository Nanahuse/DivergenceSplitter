import threading
from io import StringIO
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import pytest
from divergencesplitter_runtime.application import (
    ApplicationDiagnostics,
    ApplicationStartupValidationError,
)
from divergencesplitter_runtime.cli import (
    EXIT_COMPLETED,
    EXIT_INTERRUPTED,
    EXIT_RUNTIME_ERROR,
    EXIT_SCENARIO_MODULE_ERROR,
    EXIT_STARTUP_VALIDATION_ERROR,
    EXIT_USAGE_ERROR,
    _StatusReporter,
    main,
)
from divergencesplitter_runtime.configuration.scenario_module import (
    ScenarioModuleExecutionError,
    ScenarioModuleValidationError,
)
from divergencesplitter_runtime.diagnostics import OperationalDiagnostics
from divergencesplitter_runtime.metrics import RuntimeMetricsSnapshot


class FakeRuntime:
    instances: ClassVar[list[FakeRuntime]] = []
    outcome: ClassVar[BaseException | None] = None
    diagnostic_error: ClassVar[Exception | None] = None

    def __init__(
        self,
        scenarios: object,
        frame_source: object,
        *,
        diagnostics: ApplicationDiagnostics,
    ) -> None:
        self.scenarios = scenarios
        self.frame_source = frame_source
        self.diagnostics = diagnostics
        self.stop_requests = 0
        self.instances.append(self)

    def run(self) -> None:
        if self.diagnostic_error is not None:
            self.diagnostics.source_state_unavailable(self.diagnostic_error)
        if self.outcome is not None:
            raise self.outcome

    def request_stop(self) -> None:
        self.stop_requests += 1


class FakeStatusReporter:
    instances: ClassVar[list[FakeStatusReporter]] = []

    def __init__(self, diagnostics: object) -> None:
        self.diagnostics = diagnostics
        self.events: list[str] = []
        self.instances.append(self)

    def start(self) -> None:
        self.events.append("started")

    def stop(self) -> None:
        self.events.append("stopped")


class SignalingDiagnostics(OperationalDiagnostics):
    def __init__(self) -> None:
        super().__init__(StringIO())
        self.reported = threading.Event()
        self.snapshot: RuntimeMetricsSnapshot | None = None

    def runtime_fps(self, snapshot: RuntimeMetricsSnapshot) -> None:
        self.snapshot = snapshot
        self.reported.set()


@pytest.fixture(autouse=True)
def reset_fake_runtime() -> None:
    FakeRuntime.instances = []
    FakeRuntime.outcome = None
    FakeRuntime.diagnostic_error = None
    FakeStatusReporter.instances = []


def run_with_fake_runtime(
    outcome: BaseException | None = None,
) -> tuple[int, str, FakeRuntime, tuple[object, ...], object]:
    scenarios = (object(),)
    frame_source = object()
    stderr = StringIO()
    FakeRuntime.outcome = outcome
    with (
        patch(
            "divergencesplitter_runtime.cli.load_scenario_module",
            return_value=(scenarios, frame_source),
        ),
        patch("divergencesplitter_runtime.cli.ApplicationRuntime", FakeRuntime),
        patch("divergencesplitter_runtime.cli._StatusReporter", FakeStatusReporter),
        patch("sys.stderr", stderr),
    ):
        result = main(["scenario.py"])
    return result, stderr.getvalue(), FakeRuntime.instances[0], scenarios, frame_source


def test_runs_loaded_instances_and_returns_completed() -> None:
    result, stderr, runtime, scenarios, frame_source = run_with_fake_runtime()

    assert result == EXIT_COMPLETED
    assert "cli.completed" in stderr
    assert len(stderr.splitlines()) == 1
    assert runtime.scenarios is scenarios
    assert runtime.frame_source is frame_source
    assert FakeStatusReporter.instances[0].events == ["started", "stopped"]


def test_status_reporter_publishes_snapshot_and_stops_promptly() -> None:
    diagnostics = SignalingDiagnostics()
    reporter = _StatusReporter(diagnostics, interval_seconds=0.01)

    reporter.start()
    assert diagnostics.reported.wait(1)
    reporter.stop()

    assert diagnostics.snapshot is not None


@pytest.mark.parametrize("arguments", [[], ["one.py", "two.py"]])
def test_invalid_arguments_return_usage_error(arguments: list[str]) -> None:
    stderr = StringIO()

    with patch("sys.stderr", stderr):
        result = main(arguments)

    assert result == EXIT_USAGE_ERROR
    assert "cli.usage_failed" in stderr.getvalue()
    assert "scenario_module" in stderr.getvalue()


def test_invalid_log_level_returns_usage_error() -> None:
    stderr = StringIO()

    with patch("sys.stderr", stderr):
        result = main(["--log-level", "TRACE", "scenario.py"])

    assert result == EXIT_USAGE_ERROR
    assert "cli.usage_failed" in stderr.getvalue()
    assert "invalid choice" in stderr.getvalue()


def test_missing_module_returns_scenario_module_error(tmp_path: Path) -> None:
    stderr = StringIO()

    with patch("sys.stderr", stderr):
        result = main([str(tmp_path / "missing.py")])

    assert result == EXIT_SCENARIO_MODULE_ERROR
    assert "cli.scenario_module_failed" in stderr.getvalue()
    assert "FileNotFoundError" in stderr.getvalue()


def test_module_system_exit_is_reported_as_module_error() -> None:
    stderr = StringIO()
    error = ScenarioModuleExecutionError(SystemExit(7))

    with (
        patch(
            "divergencesplitter_runtime.cli.load_scenario_module",
            side_effect=error,
        ),
        patch("sys.stderr", stderr),
    ):
        result = main(["scenario.py"])

    assert result == EXIT_SCENARIO_MODULE_ERROR
    assert 'exception_type="SystemExit"' in stderr.getvalue()
    assert 'exception_message="7"' in stderr.getvalue()
    assert FakeRuntime.instances == []


def test_module_validation_error_is_reported_with_each_cause() -> None:
    stderr = StringIO()
    error = ScenarioModuleValidationError(
        "invalid scenario module",
        [ValueError("first"), TypeError("second")],
    )

    with (
        patch(
            "divergencesplitter_runtime.cli.load_scenario_module",
            side_effect=error,
        ),
        patch("sys.stderr", stderr),
    ):
        result = main(["scenario.py"])

    output = stderr.getvalue()
    assert result == EXIT_STARTUP_VALIDATION_ERROR
    assert "cli.startup_validation_failed" in output
    assert 'exception.0.type="ValueError"' in output
    assert 'exception.0.message="first"' in output
    assert 'exception.1.type="TypeError"' in output
    assert 'exception.1.message="second"' in output
    assert len(output.splitlines()) == 1
    assert FakeRuntime.instances == []


def test_initial_snapshot_validation_error_is_startup_failure() -> None:
    result, stderr, runtime, _, _ = run_with_fake_runtime(
        ApplicationStartupValidationError(ValueError("too many split slots"))
    )

    assert result == EXIT_STARTUP_VALIDATION_ERROR
    assert 'exception_type="ValueError"' in stderr
    assert 'exception_message="too many split slots"' in stderr
    assert runtime.stop_requests == 0


def test_runtime_exception_group_is_runtime_failure() -> None:
    result, stderr, _, _, _ = run_with_fake_runtime(
        ExceptionGroup("processing failed", [RuntimeError("boom")])
    )

    assert result == EXIT_RUNTIME_ERROR
    assert "cli.runtime_failed" in stderr
    assert 'exception.0.type="RuntimeError"' in stderr
    assert 'exception.0.message="boom"' in stderr
    assert FakeStatusReporter.instances[0].events == ["started", "stopped"]


def test_keyboard_interrupt_requests_stop_and_returns_130() -> None:
    result, stderr, runtime, _, _ = run_with_fake_runtime(KeyboardInterrupt())

    assert result == EXIT_INTERRUPTED
    assert "cli.interrupted" in stderr
    assert runtime.stop_requests == 1
    assert FakeStatusReporter.instances[0].events == ["started", "stopped"]


def test_keyboard_interrupt_during_module_load_returns_130() -> None:
    stderr = StringIO()

    with (
        patch(
            "divergencesplitter_runtime.cli.load_scenario_module",
            side_effect=KeyboardInterrupt(),
        ),
        patch("sys.stderr", stderr),
    ):
        result = main(["scenario.py"])

    assert result == EXIT_INTERRUPTED
    assert "cli.interrupted" in stderr.getvalue()
    assert FakeRuntime.instances == []


class BrokenStderr:
    def write(self, value: str) -> int:
        raise OSError("stderr unavailable")

    def flush(self) -> None:
        raise OSError("stderr unavailable")


def test_stderr_failure_does_not_replace_runtime_exit_status() -> None:
    FakeRuntime.outcome = RuntimeError("boom")
    with (
        patch(
            "divergencesplitter_runtime.cli.load_scenario_module",
            return_value=((object(),), object()),
        ),
        patch("divergencesplitter_runtime.cli.ApplicationRuntime", FakeRuntime),
        patch("sys.stderr", BrokenStderr()),
    ):
        result = main(["scenario.py"])

    assert result == EXIT_RUNTIME_ERROR


class UnprintableError(Exception):
    def __str__(self) -> str:
        raise RuntimeError("cannot format error")


def test_diagnostic_formatting_failure_does_not_stop_runtime() -> None:
    FakeRuntime.diagnostic_error = UnprintableError()

    result, _, _, _, _ = run_with_fake_runtime()

    assert result == EXIT_COMPLETED
