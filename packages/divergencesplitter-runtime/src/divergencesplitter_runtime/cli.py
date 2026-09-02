"""Minimal command-line entry point for the DivergenceSplitter runtime."""

import argparse
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Never, TextIO

from divergencesplitter import (
    Action,
    ErrorAction,
    Frame,
    FrameNormalizationError,
    FrameSourceError,
    FrameSourceState,
    LiveSplitConnection,
    MonotonicTime,
)

from divergencesplitter_runtime.application import (
    ApplicationRuntime,
    ApplicationStartupValidationError,
)
from divergencesplitter_runtime.capture import PublishResult
from divergencesplitter_runtime.configuration.scenario_module import (
    ScenarioModuleExecutionError,
    ScenarioModuleValidationError,
    load_scenario_module,
)
from divergencesplitter_runtime.livesplit.models import (
    LiveSplitResyncReason,
    LiveSplitSnapshot,
)
from divergencesplitter_runtime.livesplit.worker import (
    ActionSubmission,
    BridgeActionRequest,
)

EXIT_COMPLETED = 0
EXIT_USAGE_ERROR = 2
EXIT_SCENARIO_MODULE_ERROR = 3
EXIT_STARTUP_VALIDATION_ERROR = 4
EXIT_RUNTIME_ERROR = 5
EXIT_INTERRUPTED = 130


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE_ERROR, f"{self.prog}: usage-error: {message}\n")


class _StderrDiagnostics:
    """Report typed failure facts without configuring application logging."""

    def __init__(self, stderr: TextIO) -> None:
        self._stderr = stderr
        self._lock = threading.Lock()

    def _write(self, event: str, detail: object | None = None) -> None:
        try:
            message = event if detail is None else f"{event}: {detail}"
            with self._lock:
                print(f"divergencesplitter: {message}", file=self._stderr)
        except Exception:  # noqa: BLE001
            return

    def preparing(self) -> None:
        pass

    def prepared(self) -> None:
        pass

    def frame_received(self, publish_result: PublishResult) -> None:
        pass

    def source_error(self, error: FrameSourceError) -> None:
        self._write("source-error", _object_detail(error))

    def error_handled(
        self,
        action: ErrorAction,
        state: FrameSourceState,
    ) -> None:
        self._write("source-error-handled", f"{action.name}: {state.name}")

    def source_state_changed(
        self,
        previous: FrameSourceState | None,
        current: FrameSourceState,
    ) -> None:
        pass

    def source_state_unavailable(self, error: Exception) -> None:
        self._write("source-state-unavailable", _exception_detail(error))

    def source_closed(self) -> None:
        pass

    def stopped(self) -> None:
        pass

    def frame_processing_started(
        self,
        frame: Frame,
        processing_started_at: MonotonicTime,
    ) -> None:
        pass

    def frame_normalization_failed(self, error: FrameNormalizationError) -> None:
        self._write("frame-normalization-failed", _object_detail(error))

    def scenario_evaluation_failed(
        self,
        scenario_index: int,
        error: Exception,
    ) -> None:
        self._write(
            "scenario-evaluation-failed",
            f"scenario[{scenario_index}]: {_exception_detail(error)}",
        )

    def worker_started(self, connection: LiveSplitConnection) -> None:
        pass

    def initial_sync_failed(
        self,
        connection: LiveSplitConnection,
        error: Exception,
    ) -> None:
        self._write("bridge-initial-sync-failed", _exception_detail(error))

    def connection_lost(
        self,
        connection: LiveSplitConnection,
        error: Exception,
    ) -> None:
        self._write("bridge-connection-lost", _exception_detail(error))

    def reconnect_failed(
        self,
        connection: LiveSplitConnection,
        error: Exception,
    ) -> None:
        self._write("bridge-reconnect-failed", _exception_detail(error))

    def update_queue_overflowed(self, connection: LiveSplitConnection) -> None:
        self._write("bridge-update-queue-overflowed")

    def action_submitted(
        self,
        connection: LiveSplitConnection,
        request: BridgeActionRequest,
        result: ActionSubmission,
    ) -> None:
        if result in (ActionSubmission.REJECTED, ActionSubmission.STOPPED):
            self._write(
                "bridge-action-not-submitted",
                f"{request.action.operation}: {result.name}",
            )

    def worker_stopped(self, connection: LiveSplitConnection) -> None:
        pass

    def snapshot_failed(self, action: Action, error: Exception) -> None:
        self._write(
            "bridge-snapshot-failed",
            f"{action.operation}: {_exception_detail(error)}",
        )

    def snapshot_mismatched(
        self,
        action: Action,
        expected: LiveSplitSnapshot,
        actual: LiveSplitSnapshot,
    ) -> None:
        self._write("bridge-snapshot-mismatched", action.operation)

    def action_precondition_failed(
        self,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None:
        self._write("bridge-action-precondition-failed", action.operation)

    def action_succeeded(
        self,
        action: Action,
        snapshot: LiveSplitSnapshot,
    ) -> None:
        pass

    def action_rejected(
        self,
        action: Action,
        snapshot: LiveSplitSnapshot,
        code: int | None,
        message: str,
    ) -> None:
        self._write(
            "bridge-action-rejected",
            f"{action.operation}: code={code!r}: {message}",
        )

    def action_result_unknown(
        self,
        action: Action,
        snapshot: LiveSplitSnapshot,
        error: Exception,
    ) -> None:
        self._write(
            "bridge-action-result-unknown",
            f"{action.operation}: {_exception_detail(error)}",
        )

    def gap_detected(
        self,
        connection: LiveSplitConnection,
        baseline: LiveSplitSnapshot,
        received_session_id: int,
        received_event_sequence: int,
    ) -> None:
        self._write("bridge-gap-detected")

    def heartbeat_received(
        self,
        connection: LiveSplitConnection,
        session_id: int,
        event_sequence: int,
    ) -> None:
        pass

    def resync_started(
        self,
        connection: LiveSplitConnection,
        reason: LiveSplitResyncReason,
    ) -> None:
        pass

    def resync_completed(
        self,
        connection: LiveSplitConnection,
        reason: LiveSplitResyncReason,
        previous: LiveSplitSnapshot,
        current: LiveSplitSnapshot,
    ) -> None:
        pass


def main(argv: Sequence[str] | None = None) -> int:
    """Run one trusted scenario module and return a process exit status."""

    parser = _ArgumentParser(prog="divergencesplitter")
    parser.add_argument("scenario_module", type=Path)
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else EXIT_USAGE_ERROR

    try:
        scenarios, frame_source = load_scenario_module(arguments.scenario_module)
    except KeyboardInterrupt:
        _write_failure("interrupted", stderr=sys.stderr)
        return EXIT_INTERRUPTED
    except ScenarioModuleExecutionError as error:
        _write_failure("scenario-module-error", error.error, stderr=sys.stderr)
        return EXIT_SCENARIO_MODULE_ERROR
    except ScenarioModuleValidationError as error:
        _write_failure("startup-validation-error", error, stderr=sys.stderr)
        return EXIT_STARTUP_VALIDATION_ERROR

    try:
        runtime = ApplicationRuntime(
            scenarios,
            frame_source,
            diagnostics=_StderrDiagnostics(sys.stderr),
        )
    except KeyboardInterrupt:
        _write_failure("interrupted", stderr=sys.stderr)
        return EXIT_INTERRUPTED
    except ExceptionGroup as error:
        _write_failure("startup-validation-error", error, stderr=sys.stderr)
        return EXIT_STARTUP_VALIDATION_ERROR
    except Exception as error:  # noqa: BLE001
        _write_failure("runtime-error", error, stderr=sys.stderr)
        return EXIT_RUNTIME_ERROR

    try:
        runtime.run()
    except KeyboardInterrupt:
        runtime.request_stop()
        _write_failure("interrupted", stderr=sys.stderr)
        return EXIT_INTERRUPTED
    except ApplicationStartupValidationError as error:
        _write_failure("startup-validation-error", error.error, stderr=sys.stderr)
        return EXIT_STARTUP_VALIDATION_ERROR
    except Exception as error:  # noqa: BLE001
        _write_failure("runtime-error", error, stderr=sys.stderr)
        return EXIT_RUNTIME_ERROR
    return EXIT_COMPLETED


def _write_failure(
    category: str,
    error: BaseException | None = None,
    *,
    stderr: TextIO,
) -> None:
    try:
        print(f"divergencesplitter: {category}", file=stderr)
        if error is not None:
            _write_exception(error, stderr=stderr)
    except Exception:  # noqa: BLE001
        return


def _write_exception(
    error: BaseException,
    *,
    stderr: TextIO,
    indent: str = "  ",
) -> None:
    print(f"{indent}{_exception_detail(error)}", file=stderr)
    if isinstance(error, BaseExceptionGroup):
        for nested in error.exceptions:
            _write_exception(nested, stderr=stderr, indent=f"{indent}  ")


def _exception_detail(error: BaseException) -> str:
    return _object_detail(error)


def _object_detail(value: object) -> str:
    try:
        return f"{type(value).__name__}: {value}"
    except Exception:  # noqa: BLE001
        return type(value).__name__
