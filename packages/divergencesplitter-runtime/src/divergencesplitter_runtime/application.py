"""Top-level lifecycle for Capture, Processing, and Bridge workers."""

import logging
import threading
from collections.abc import Callable
from typing import Protocol

from divergencesplitter.frame.source import FrameSource
from divergencesplitter.scenario.models import Scenario

from divergencesplitter_runtime.capture import (
    CaptureDiagnostics,
    CaptureStateMachine,
    LatestFrameBuffer,
)
from divergencesplitter_runtime.configuration.validation import (
    validate_scenarios,
    validate_split_count,
)
from divergencesplitter_runtime.livesplit.worker import (
    BridgeWorker,
    BridgeWorkerDiagnostics,
)
from divergencesplitter_runtime.processing import (
    ProcessingDiagnostics,
    ProcessingRuntime,
)
from divergencesplitter_runtime.scenario import ScenarioRuntime


class ApplicationDiagnostics(
    CaptureDiagnostics,
    ProcessingDiagnostics,
    BridgeWorkerDiagnostics,
    Protocol,
):
    """Combined typed diagnostics consumed by the application components."""

    def scenario_logger(
        self,
        scenario_index: int,
    ) -> logging.Logger | logging.LoggerAdapter: ...

    def runtime_started(self) -> None: ...


class ApplicationStartupValidationError(Exception):
    """A constraint requiring the initial LiveSplit snapshot was violated."""

    def __init__(self, error: ValueError) -> None:
        self.error = error
        super().__init__(str(error))


class ApplicationRuntime:
    """Coordinate startup and cooperative shutdown of all runtime threads."""

    def __init__(
        self,
        scenarios: tuple[Scenario, ...],
        frame_source: FrameSource,
        *,
        diagnostics: ApplicationDiagnostics,
    ) -> None:
        validate_scenarios(scenarios)
        self._diagnostics = diagnostics
        self._frame_buffer = LatestFrameBuffer()
        self._scenario_runtimes = tuple(
            ScenarioRuntime(item, logger=diagnostics.scenario_logger(index))
            for index, item in enumerate(scenarios)
        )
        self._workers = tuple(
            BridgeWorker(item.connection, diagnostics=diagnostics) for item in scenarios
        )
        self._capture = CaptureStateMachine(
            frame_source,
            self._frame_buffer,
            diagnostics=diagnostics,
        )
        self._processing = ProcessingRuntime(
            self._scenario_runtimes,
            self._workers,
            self._frame_buffer,
            frame_source.normalizer,
            diagnostics=diagnostics,
        )
        self._scenarios = scenarios
        self._stop_requested = threading.Event()

    def request_stop(self) -> None:
        self._stop_requested.set()
        self._capture.request_stop()
        self._processing.request_stop()
        for worker in self._workers:
            worker.request_stop()

    def run(self) -> None:
        worker_threads = tuple(
            threading.Thread(target=worker.run, name=f"bridge-worker-{index}")
            for index, worker in enumerate(self._workers)
        )
        for thread in worker_threads:
            thread.start()

        capture_error: list[BaseException] = []
        processing_error: list[BaseException] = []
        capture_thread: threading.Thread | None = None
        processing_thread: threading.Thread | None = None
        try:
            self._initialize_scenarios()
            if self._stop_requested.is_set():
                return

            processing_thread = threading.Thread(
                target=lambda: self._run_recording_errors(
                    self._processing.run,
                    processing_error,
                ),
                name="processing",
            )
            capture_thread = threading.Thread(
                target=lambda: self._run_recording_errors(
                    self._capture.run,
                    capture_error,
                ),
                name="capture",
            )
            self._diagnostics.runtime_started()
            processing_thread.start()
            capture_thread.start()
            capture_thread.join()
        finally:
            self.request_stop()
            if capture_thread is not None and capture_thread.is_alive():
                capture_thread.join()
            if processing_thread is not None:
                processing_thread.join()
            for thread in worker_threads:
                thread.join()

        if capture_error:
            raise capture_error[0]
        if processing_error:
            raise processing_error[0]

    def _initialize_scenarios(self) -> None:
        for worker in self._workers:
            worker.wait_until_initialized()
        for scenario, runtime, worker in zip(
            self._scenarios,
            self._scenario_runtimes,
            self._workers,
            strict=True,
        ):
            updates = worker.drain_updates()
            if not updates:
                raise RuntimeError("Bridge worker produced no initial update")
            initial = updates[0]
            try:
                validate_split_count(scenario, initial.snapshot)
            except ValueError as error:
                raise ApplicationStartupValidationError(error) from error
            runtime.apply_livesplit_update(initial)
            for update in updates[1:]:
                runtime.apply_livesplit_update(update)

    def _run_recording_errors(
        self,
        operation: Callable[[], None],
        errors: list[BaseException],
    ) -> None:
        try:
            operation()
        except BaseException as error:  # noqa: BLE001
            errors.append(error)
            self.request_stop()
