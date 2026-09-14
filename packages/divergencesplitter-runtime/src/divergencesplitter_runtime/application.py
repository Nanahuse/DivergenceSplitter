"""Top-level lifecycle for Capture, Processing, and Bridge workers."""

import logging
import threading
from collections.abc import Callable
from typing import Protocol

from divergencesplitter.frame.source import FrameSource

from divergencesplitter_runtime.capture import (
    CaptureDiagnostics,
    CaptureStateMachine,
    LatestFrameBuffer,
)
from divergencesplitter_runtime.configuration.validation import (
    validate_instances,
)
from divergencesplitter_runtime.instance_runtime import (
    InstanceRuntime,
    InstanceRuntimeState,
    InstanceStatus,
)
from divergencesplitter_runtime.instances import ScenarioInstance
from divergencesplitter_runtime.livesplit.worker import (
    BridgeWorker,
    BridgeWorkerDiagnostics,
)
from divergencesplitter_runtime.processing import (
    ProcessingDiagnostics,
    ProcessingRuntime,
)


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

    def instances_changed(self, statuses: tuple[InstanceStatus, ...]) -> None: ...

    def runtime_started(self) -> None:
        """Shared Capture/Processing is starting; instances may still be connecting."""
        ...


class ApplicationStartupValidationError(Exception):
    """A constraint requiring the initial LiveSplit snapshot was violated."""

    def __init__(self, error: ValueError) -> None:
        self.error = error
        super().__init__(str(error))


class AllInstancesFailedError(RuntimeError):
    """Every configured instance failed; shared runtime resources are closed."""

    def __init__(self, statuses: tuple[InstanceStatus, ...]) -> None:
        self.statuses = statuses
        details = "; ".join(
            f"Instance {status.scenario_index}: {status.error or 'failed'}"
            for status in statuses
        )
        super().__init__(f"All LiveSplit instances failed: {details}")


class ApplicationRuntime:
    """Coordinate startup and cooperative shutdown of all runtime threads."""

    def __init__(
        self,
        instances: tuple[ScenarioInstance, ...],
        frame_source: FrameSource,
        *,
        diagnostics: ApplicationDiagnostics,
    ) -> None:
        validate_instances(
            tuple((instance.connection, instance.scenario) for instance in instances)
        )
        self._diagnostics = diagnostics
        self._frame_source = frame_source
        self._frame_buffer = LatestFrameBuffer()
        self._instances = tuple(
            InstanceRuntime(
                instance.scenario,
                BridgeWorker(instance.connection, diagnostics=diagnostics),
                logger=diagnostics.scenario_logger(index),
            )
            for index, instance in enumerate(instances)
        )
        self._capture = CaptureStateMachine(
            frame_source,
            self._frame_buffer,
            diagnostics=diagnostics,
        )
        self._processing = ProcessingRuntime(
            self._instances,
            self._frame_buffer,
            frame_source.normalizer,
            diagnostics=diagnostics,
        )
        self._stop_requested = threading.Event()
        self._diagnostics.instances_changed(self.instance_statuses())

    @property
    def instances(self) -> tuple[InstanceRuntime, ...]:
        return self._instances

    def instance_statuses(self) -> tuple[InstanceStatus, ...]:
        return tuple(
            instance.status(index) for index, instance in enumerate(self._instances)
        )

    def request_stop(self) -> None:
        self._stop_requested.set()
        self._capture.request_stop()
        self._processing.request_stop()
        for instance in self._instances:
            instance.worker.request_stop()

    def run(self) -> None:
        worker_threads = tuple(
            threading.Thread(target=worker.run, name=f"bridge-worker-{index}")
            for index, instance in enumerate(self._instances)
            for worker in (instance.worker,)
        )
        for thread in worker_threads:
            thread.start()

        instance_failure: AllInstancesFailedError | None = None
        last_statuses = self.instance_statuses()
        capture_error: list[BaseException] = []
        processing_error: list[BaseException] = []
        capture_thread: threading.Thread | None = None
        capture_started = False
        processing_thread: threading.Thread | None = None
        try:
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
            capture_started = True
            while True:
                last_statuses = self.instance_statuses()
                self._diagnostics.instances_changed(last_statuses)
                if (
                    not self._stop_requested.is_set()
                    and last_statuses
                    and all(
                        status.state is InstanceRuntimeState.FAILED
                        for status in last_statuses
                    )
                ):
                    instance_failure = AllInstancesFailedError(last_statuses)
                    break
                if not capture_thread.is_alive():
                    break
                capture_thread.join(0.05)
        finally:
            self.request_stop()
            if capture_thread is not None and capture_thread.is_alive():
                capture_thread.join()
            if not capture_started:
                self._frame_source.close()
                self._diagnostics.source_closed()
                self._diagnostics.stopped()
            if processing_thread is not None:
                processing_thread.join()
            for thread in worker_threads:
                thread.join()
            for index, instance in enumerate(self._instances):
                instance.stop()
                # Drop stale LiveSplit Run info once the Processing thread that
                # would report the change has already stopped.
                self._diagnostics.instance_run_changed(index, None)
            # Keep failed outcomes visible after teardown; other instances stopped.
            self._diagnostics.instances_changed(
                tuple(
                    status
                    if status.state is InstanceRuntimeState.FAILED
                    else InstanceStatus(
                        status.scenario_index,
                        InstanceRuntimeState.STOPPED,
                        status.error,
                    )
                    for status in last_statuses
                )
            )

        if capture_error:
            raise capture_error[0]
        if processing_error:
            raise processing_error[0]
        if instance_failure is not None:
            raise instance_failure

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
